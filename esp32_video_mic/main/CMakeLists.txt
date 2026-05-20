idf_component_register(SRCS "main.c"
        "src/app_wifi.c"
        "src/app_camera.c"
        "src/app_audio.c"
        "src/app_stream_cam.c"
        "src/app_stream_audio.c"
                    INCLUDE_DIRS "inc"
                    REQUIRES 
                    esp32-camera 
                    esp_wifi nvs_flash 
                    esp_http_client 
                    esp-tls 
                    json
                    driver
                    esp_websocket_client
                    esp_event)
