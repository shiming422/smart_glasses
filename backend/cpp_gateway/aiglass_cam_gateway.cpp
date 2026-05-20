#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <chrono>
#include <cstdlib>
#include <deque>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
using TimePoint = Clock::time_point;

constexpr uint32_t kCamMagic = 0x43474941;     // "AIGC" little-endian
constexpr uint8_t kCamVersion = 1;
constexpr uint8_t kCamHeaderLen = 32;
constexpr uint32_t kGatewayMagic = 0x46474941; // "AIGF" little-endian
constexpr uint8_t kGatewayVersion = 1;
constexpr uint16_t kGatewayHeaderLen = 32;
constexpr uint8_t kRecordJpeg = 1;
constexpr uint8_t kRecordStatsJson = 2;

#pragma pack(push, 1)
struct CamUdpHeader {
    uint32_t magic;
    uint8_t version;
    uint8_t header_len;
    uint8_t flags;
    uint8_t source_id;
    uint32_t frame_id;
    uint32_t timestamp_ms;
    uint32_t frame_len;
    uint32_t frame_crc32;
    uint16_t chunk_index;
    uint16_t chunk_count;
    uint16_t payload_len;
    uint16_t reserved;
};

struct GatewayRecordHeader {
    uint32_t magic;
    uint8_t version;
    uint8_t type;
    uint16_t header_len;
    uint32_t frame_id;
    uint64_t timestamp_ms;
    uint32_t payload_len;
    uint32_t payload_crc32;
    uint32_t reserved;
};
#pragma pack(pop)

static_assert(sizeof(CamUdpHeader) == 32, "CamUdpHeader must stay 32 bytes");
static_assert(sizeof(GatewayRecordHeader) == 32, "GatewayRecordHeader must stay 32 bytes");

int env_int(const char* name, int default_value, int min_value, int max_value) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || *raw == '\0') {
        return default_value;
    }
    char* end = nullptr;
    long value = std::strtol(raw, &end, 10);
    if (end == raw) {
        return default_value;
    }
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return static_cast<int>(value);
}

std::string env_string(const char* name, const char* default_value) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || *raw == '\0') {
        return std::string(default_value);
    }
    return std::string(raw);
}

uint32_t crc32_bytes(const uint8_t* data, size_t len) {
    static uint32_t table[256];
    static bool initialized = false;
    if (!initialized) {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int j = 0; j < 8; ++j) {
                c = (c & 1U) ? (0xEDB88320U ^ (c >> 1U)) : (c >> 1U);
            }
            table[i] = c;
        }
        initialized = true;
    }

    uint32_t c = 0xFFFFFFFFU;
    for (size_t i = 0; i < len; ++i) {
        c = table[(c ^ data[i]) & 0xFFU] ^ (c >> 8U);
    }
    return c ^ 0xFFFFFFFFU;
}

uint64_t now_ms() {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            Clock::now().time_since_epoch()
        ).count()
    );
}

int64_t age_ms(TimePoint point) {
    if (point.time_since_epoch().count() == 0) {
        return -1;
    }
    return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - point).count();
}

std::string addr_to_string(const sockaddr_in& addr) {
    char ip[INET_ADDRSTRLEN] = {};
    inet_ntop(AF_INET, &addr.sin_addr, ip, sizeof(ip));
    std::ostringstream oss;
    oss << ip << ":" << ntohs(addr.sin_port);
    return oss.str();
}

struct Assembly {
    uint8_t source_id = 0;
    uint32_t frame_id = 0;
    uint32_t timestamp_ms = 0;
    uint32_t frame_len = 0;
    uint32_t frame_crc32 = 0;
    uint16_t chunk_count = 0;
    TimePoint created_at{};
    sockaddr_in addr{};
    std::vector<std::vector<uint8_t>> chunks;
    std::vector<uint8_t> received;
    uint16_t received_count = 0;
    uint32_t received_bytes = 0;
};

struct Stats {
    uint64_t packets = 0;
    uint64_t completed_frames = 0;
    uint64_t stale_chunks = 0;
    uint64_t duplicate_chunks = 0;
    uint64_t invalid_packets = 0;
    uint64_t crc_errors = 0;
    uint64_t timeouts = 0;
    uint64_t dropped_incomplete = 0;
    uint64_t oversize_frames = 0;
    uint8_t last_source_id = 0;
    uint32_t last_frame_id = 0;
    uint32_t last_frame_len = 0;
    uint32_t last_timestamp_ms = 0;
    std::string last_addr;
    TimePoint last_completed_at{};
    std::deque<std::pair<TimePoint, uint32_t>> completed_window;
    std::deque<std::pair<TimePoint, std::string>> event_window;
};

struct GatewayState {
    int udp_port = 22345;
    int tcp_port = 22346;
    int ttl_ms = 250;
    int max_frame_bytes = 512 * 1024;
    std::string tcp_host = "127.0.0.1";
    int tcp_fd = -1;
    TimePoint next_tcp_attempt{};
    std::unordered_map<uint8_t, Assembly> assemblies;
    Stats stats;
};

void note_event(Stats& stats, const std::string& kind, TimePoint now) {
    stats.event_window.emplace_back(now, kind);
}

void prune_windows(Stats& stats, TimePoint now) {
    const auto cutoff = now - std::chrono::seconds(10);
    while (!stats.completed_window.empty() && stats.completed_window.front().first < cutoff) {
        stats.completed_window.pop_front();
    }
    while (!stats.event_window.empty() && stats.event_window.front().first < cutoff) {
        stats.event_window.pop_front();
    }
}

double complete_fps(Stats& stats, TimePoint now) {
    prune_windows(stats, now);
    if (stats.completed_window.size() < 2) {
        return static_cast<double>(stats.completed_window.size());
    }
    const auto span_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        stats.completed_window.back().first - stats.completed_window.front().first
    ).count();
    const double span = std::max<int64_t>(1, span_ms) / 1000.0;
    return static_cast<double>(stats.completed_window.size() - 1) / span;
}

uint32_t avg_jpeg_bytes(Stats& stats, TimePoint now) {
    prune_windows(stats, now);
    if (stats.completed_window.empty()) {
        return 0;
    }
    uint64_t total = 0;
    for (const auto& item : stats.completed_window) {
        total += item.second;
    }
    return static_cast<uint32_t>(total / stats.completed_window.size());
}

double drop_ratio_10s(Stats& stats, TimePoint now) {
    prune_windows(stats, now);
    uint64_t drops = 0;
    for (const auto& item : stats.event_window) {
        if (item.second != "complete") {
            ++drops;
        }
    }
    const uint64_t complete = stats.completed_window.size();
    const uint64_t total = complete + drops;
    if (total == 0) {
        return 0.0;
    }
    return static_cast<double>(drops) / static_cast<double>(total);
}

void close_tcp(GatewayState& state) {
    if (state.tcp_fd >= 0) {
        close(state.tcp_fd);
        state.tcp_fd = -1;
    }
}

bool connect_tcp(GatewayState& state) {
    TimePoint now = Clock::now();
    if (state.tcp_fd >= 0) {
        return true;
    }
    if (state.next_tcp_attempt.time_since_epoch().count() != 0 && now < state.next_tcp_attempt) {
        return false;
    }
    state.next_tcp_attempt = now + std::chrono::seconds(1);

    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* result = nullptr;
    const std::string port_text = std::to_string(state.tcp_port);
    int rc = getaddrinfo(state.tcp_host.c_str(), port_text.c_str(), &hints, &result);
    if (rc != 0) {
        std::cerr << "[CAM GW] python resolve failed: " << gai_strerror(rc) << std::endl;
        return false;
    }

    int fd = -1;
    for (addrinfo* ai = result; ai != nullptr; ai = ai->ai_next) {
        fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0) {
            continue;
        }
        timeval timeout{};
        timeout.tv_sec = 1;
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        if (connect(fd, ai->ai_addr, ai->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);

    if (fd < 0) {
        return false;
    }

    state.tcp_fd = fd;
    std::cout << "[CAM GW] connected to python " << state.tcp_host << ":" << state.tcp_port << std::endl;
    return true;
}

bool send_all(int fd, const uint8_t* data, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(fd, data + sent, len - sent, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return false;
        }
        if (n == 0) {
            return false;
        }
        sent += static_cast<size_t>(n);
    }
    return true;
}

bool send_record(GatewayState& state, uint8_t type, uint32_t frame_id, uint64_t timestamp_ms,
                 const std::vector<uint8_t>& payload) {
    if (!connect_tcp(state)) {
        return false;
    }

    GatewayRecordHeader hdr{};
    hdr.magic = kGatewayMagic;
    hdr.version = kGatewayVersion;
    hdr.type = type;
    hdr.header_len = kGatewayHeaderLen;
    hdr.frame_id = frame_id;
    hdr.timestamp_ms = timestamp_ms;
    hdr.payload_len = static_cast<uint32_t>(payload.size());
    hdr.payload_crc32 = payload.empty() ? 0 : crc32_bytes(payload.data(), payload.size());

    if (!send_all(state.tcp_fd, reinterpret_cast<const uint8_t*>(&hdr), sizeof(hdr)) ||
        (!payload.empty() && !send_all(state.tcp_fd, payload.data(), payload.size()))) {
        std::cerr << "[CAM GW] python connection lost" << std::endl;
        close_tcp(state);
        return false;
    }
    return true;
}

std::string stats_json(GatewayState& state) {
    TimePoint now = Clock::now();
    Stats& s = state.stats;
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(3);
    oss << "{";
    oss << "\"protocol\":\"cpp_gateway\"";
    oss << ",\"udp_port\":" << state.udp_port;
    oss << ",\"udp_frame_ttl_ms\":" << state.ttl_ms;
    oss << ",\"udp_max_frame_bytes\":" << state.max_frame_bytes;
    oss << ",\"packets\":" << s.packets;
    oss << ",\"completed_frames\":" << s.completed_frames;
    oss << ",\"complete_fps\":" << complete_fps(s, now);
    oss << ",\"avg_jpeg_bytes\":" << avg_jpeg_bytes(s, now);
    oss << ",\"drop_ratio_10s\":" << drop_ratio_10s(s, now);
    oss << ",\"stale_chunks\":" << s.stale_chunks;
    oss << ",\"duplicate_chunks\":" << s.duplicate_chunks;
    oss << ",\"invalid_packets\":" << s.invalid_packets;
    oss << ",\"crc_errors\":" << s.crc_errors;
    oss << ",\"timeouts\":" << s.timeouts;
    oss << ",\"dropped_incomplete\":" << s.dropped_incomplete;
    oss << ",\"oversize_frames\":" << s.oversize_frames;
    oss << ",\"last_source_id\":" << static_cast<unsigned int>(s.last_source_id);
    oss << ",\"last_frame_id\":" << s.last_frame_id;
    oss << ",\"last_frame_len\":" << s.last_frame_len;
    oss << ",\"last_timestamp_ms\":" << s.last_timestamp_ms;
    oss << ",\"last_frame_age_ms\":" << age_ms(s.last_completed_at);
    if (s.last_addr.empty()) {
        oss << ",\"last_addr\":null";
    } else {
        oss << ",\"last_addr\":\"" << s.last_addr << "\"";
    }
    oss << "}";
    return oss.str();
}

void send_stats(GatewayState& state) {
    const std::string text = stats_json(state);
    std::vector<uint8_t> payload(text.begin(), text.end());
    send_record(state, kRecordStatsJson, state.stats.last_frame_id, now_ms(), payload);
}

void clear_timeouts(GatewayState& state) {
    const TimePoint now = Clock::now();
    std::vector<uint8_t> stale_sources;
    for (const auto& item : state.assemblies) {
        const Assembly& assembly = item.second;
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - assembly.created_at
        ).count();
        if (elapsed > state.ttl_ms) {
            stale_sources.push_back(item.first);
        }
    }
    for (uint8_t source_id : stale_sources) {
        state.assemblies.erase(source_id);
        state.stats.timeouts += 1;
        note_event(state.stats, "timeout", now);
    }
}

void complete_assembly(GatewayState& state, Assembly& assembly) {
    std::vector<uint8_t> jpeg;
    jpeg.reserve(assembly.frame_len);
    for (const auto& chunk : assembly.chunks) {
        jpeg.insert(jpeg.end(), chunk.begin(), chunk.end());
    }

    const TimePoint now = Clock::now();
    if (jpeg.size() != assembly.frame_len) {
        state.stats.invalid_packets += 1;
        note_event(state.stats, "invalid", now);
        return;
    }
    const uint32_t crc = crc32_bytes(jpeg.data(), jpeg.size());
    if (crc != assembly.frame_crc32) {
        state.stats.crc_errors += 1;
        note_event(state.stats, "crc", now);
        return;
    }

    state.stats.completed_frames += 1;
    state.stats.last_source_id = assembly.source_id;
    state.stats.last_frame_id = assembly.frame_id;
    state.stats.last_frame_len = assembly.frame_len;
    state.stats.last_timestamp_ms = assembly.timestamp_ms;
    state.stats.last_addr = addr_to_string(assembly.addr);
    state.stats.last_completed_at = now;
    state.stats.completed_window.emplace_back(now, assembly.frame_len);
    note_event(state.stats, "complete", now);

    send_record(state, kRecordJpeg, assembly.frame_id, assembly.timestamp_ms, jpeg);
}

void handle_udp_packet(GatewayState& state, const uint8_t* data, size_t len, const sockaddr_in& addr) {
    const TimePoint now = Clock::now();
    state.stats.packets += 1;
    clear_timeouts(state);

    if (len < sizeof(CamUdpHeader)) {
        state.stats.invalid_packets += 1;
        note_event(state.stats, "invalid", now);
        return;
    }

    CamUdpHeader hdr{};
    memcpy(&hdr, data, sizeof(hdr));
    if (hdr.magic != kCamMagic ||
        hdr.version != kCamVersion ||
        hdr.header_len != kCamHeaderLen ||
        hdr.flags != 0 ||
        hdr.chunk_count == 0 ||
        hdr.chunk_index >= hdr.chunk_count ||
        hdr.frame_len == 0 ||
        hdr.payload_len == 0 ||
        len != static_cast<size_t>(hdr.header_len) + static_cast<size_t>(hdr.payload_len)) {
        if (hdr.frame_len > static_cast<uint32_t>(state.max_frame_bytes)) {
            state.stats.oversize_frames += 1;
        } else {
            state.stats.invalid_packets += 1;
        }
        note_event(state.stats, "invalid", now);
        return;
    }
    if (hdr.frame_len > static_cast<uint32_t>(state.max_frame_bytes)) {
        state.stats.oversize_frames += 1;
        note_event(state.stats, "invalid", now);
        return;
    }

    auto assembly_it = state.assemblies.find(hdr.source_id);
    if (assembly_it != state.assemblies.end()) {
        Assembly& old = assembly_it->second;
        if (hdr.frame_id < old.frame_id) {
            state.stats.stale_chunks += 1;
            note_event(state.stats, "stale", now);
            return;
        }
        if (hdr.frame_id > old.frame_id) {
            if (old.received_count < old.chunk_count) {
                state.stats.dropped_incomplete += 1;
                note_event(state.stats, "drop_newer", now);
            }
            state.assemblies.erase(assembly_it);
            assembly_it = state.assemblies.end();
        }
    }

    if (assembly_it == state.assemblies.end()) {
        Assembly assembly;
        assembly.source_id = hdr.source_id;
        assembly.frame_id = hdr.frame_id;
        assembly.timestamp_ms = hdr.timestamp_ms;
        assembly.frame_len = hdr.frame_len;
        assembly.frame_crc32 = hdr.frame_crc32;
        assembly.chunk_count = hdr.chunk_count;
        assembly.created_at = now;
        assembly.addr = addr;
        assembly.chunks.resize(hdr.chunk_count);
        assembly.received.assign(hdr.chunk_count, 0);
        auto inserted = state.assemblies.emplace(hdr.source_id, std::move(assembly));
        assembly_it = inserted.first;
    }

    Assembly& assembly = assembly_it->second;
    if (assembly.frame_id != hdr.frame_id ||
        assembly.frame_len != hdr.frame_len ||
        assembly.frame_crc32 != hdr.frame_crc32 ||
        assembly.chunk_count != hdr.chunk_count) {
        state.stats.invalid_packets += 1;
        note_event(state.stats, "invalid", now);
        return;
    }

    if (assembly.received[hdr.chunk_index] != 0) {
        state.stats.duplicate_chunks += 1;
        return;
    }

    const uint8_t* payload = data + hdr.header_len;
    assembly.chunks[hdr.chunk_index].assign(payload, payload + hdr.payload_len);
    assembly.received[hdr.chunk_index] = 1;
    assembly.received_count += 1;
    assembly.received_bytes += hdr.payload_len;

    if (assembly.received_count != assembly.chunk_count) {
        return;
    }

    Assembly complete = std::move(assembly);
    state.assemblies.erase(hdr.source_id);
    complete_assembly(state, complete);
}

int create_udp_socket(int port) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        std::cerr << "[CAM GW] UDP socket failed: " << strerror(errno) << std::endl;
        return -1;
    }

    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        std::cerr << "[CAM GW] UDP bind failed on " << port << ": " << strerror(errno) << std::endl;
        close(fd);
        return -1;
    }

    int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) {
        fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    }
    std::cout << "[CAM GW] UDP listening on 0.0.0.0:" << port << std::endl;
    return fd;
}

} // namespace

int main() {
    GatewayState state;
    state.udp_port = env_int("AIGLASS_CAMERA_UDP_PORT", 22345, 1, 65535);
    state.ttl_ms = env_int("AIGLASS_CAMERA_UDP_FRAME_TTL_MS", 250, 50, 5000);
    state.max_frame_bytes = env_int("AIGLASS_CAMERA_UDP_MAX_FRAME_BYTES", 512 * 1024, 64 * 1024, 4 * 1024 * 1024);
    state.tcp_host = env_string("AIGLASS_CAMERA_GATEWAY_TCP_HOST", "127.0.0.1");
    state.tcp_port = env_int("AIGLASS_CAMERA_GATEWAY_TCP_PORT", 22346, 1, 65535);

    int udp_fd = create_udp_socket(state.udp_port);
    if (udp_fd < 0) {
        return 2;
    }

    TimePoint next_stats = Clock::now() + std::chrono::seconds(1);
    std::vector<uint8_t> buffer(65536);

    while (true) {
        connect_tcp(state);

        pollfd pfd{};
        pfd.fd = udp_fd;
        pfd.events = POLLIN;
        int rc = poll(&pfd, 1, 20);
        if (rc > 0 && (pfd.revents & POLLIN)) {
            while (true) {
                sockaddr_in from{};
                socklen_t from_len = sizeof(from);
                ssize_t n = recvfrom(
                    udp_fd,
                    buffer.data(),
                    buffer.size(),
                    0,
                    reinterpret_cast<sockaddr*>(&from),
                    &from_len
                );
                if (n < 0) {
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        break;
                    }
                    if (errno == EINTR) {
                        continue;
                    }
                    std::cerr << "[CAM GW] recvfrom failed: " << strerror(errno) << std::endl;
                    break;
                }
                if (n > 0) {
                    handle_udp_packet(state, buffer.data(), static_cast<size_t>(n), from);
                }
            }
        }

        clear_timeouts(state);
        if (Clock::now() >= next_stats) {
            send_stats(state);
            next_stats = Clock::now() + std::chrono::seconds(1);
        }
    }

    close_tcp(state);
    close(udp_fd);
    return 0;
}
