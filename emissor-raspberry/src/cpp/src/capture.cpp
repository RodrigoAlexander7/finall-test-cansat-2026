#include "capture.hpp"

#include <iostream>
#include <stdexcept>

namespace cansat {

CameraCapture::CameraCapture(int device_id, int width, int height, int fps)
    : device_id_(device_id), width_(width), height_(height), fps_(fps), opened_(false) {}

CameraCapture::~CameraCapture() {
    release();
}

void CameraCapture::open() {
    if (opened_) {
        return;
    }

    cap_.open(device_id_, cv::CAP_V4L2);
    if (!cap_.isOpened()) {
        throw std::runtime_error("No se pudo abrir la camara");
    }

    cap_.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M', 'J', 'P', 'G'));
    cap_.set(cv::CAP_PROP_FRAME_WIDTH, width_);
    cap_.set(cv::CAP_PROP_FRAME_HEIGHT, height_);
    cap_.set(cv::CAP_PROP_FPS, fps_);
    cap_.set(cv::CAP_PROP_BUFFERSIZE, 1);

    cv::Mat warmup;
    for (int i = 0; i < 5; ++i) {
        cap_.read(warmup);
    }

    opened_ = true;

    std::cout << "[capture] Camara abierta "
              << cap_.get(cv::CAP_PROP_FRAME_WIDTH) << "x"
              << cap_.get(cv::CAP_PROP_FRAME_HEIGHT) << " @ "
              << cap_.get(cv::CAP_PROP_FPS) << " fps" << std::endl;
}

void CameraCapture::release() {
    if (opened_) {
        cap_.release();
        opened_ = false;
        std::cout << "[capture] Camara liberada" << std::endl;
    }
}

bool CameraCapture::is_open() const {
    return opened_ && cap_.isOpened();
}

bool CameraCapture::grab_frame(cv::Mat& frame) {
    if (!opened_) {
        return false;
    }

    if (!cap_.read(frame)) {
        return false;
    }

    return !frame.empty();
}

}  // namespace cansat
