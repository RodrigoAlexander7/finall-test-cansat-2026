#pragma once

#include <opencv2/core.hpp>
#include <opencv2/videoio.hpp>

namespace cansat {

class CameraCapture {
public:
    explicit CameraCapture(int device_id, int width, int height, int fps);
    ~CameraCapture();

    CameraCapture(const CameraCapture&) = delete;
    CameraCapture& operator=(const CameraCapture&) = delete;

    void open();
    void release();
    bool is_open() const;
    bool grab_frame(cv::Mat& frame);

private:
    cv::VideoCapture cap_;
    int device_id_;
    int width_;
    int height_;
    int fps_;
    bool opened_;
};

}  // namespace cansat
