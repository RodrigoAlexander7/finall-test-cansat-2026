cmake_minimum_required(VERSION 3.16)
project(cansat_image_tool LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs videoio)

add_executable(cansat_image_tool
    src/main.cpp
    src/capture.cpp
    src/encoding.cpp
)

target_include_directories(cansat_image_tool PRIVATE include)
target_link_libraries(cansat_image_tool PRIVATE ${OpenCV_LIBS})
