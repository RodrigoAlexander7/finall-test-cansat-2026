#include "encoding.hpp"

#include <opencv2/imgcodecs.hpp>

namespace cansat {

JpegEncoder::JpegEncoder(int quality) : quality_(quality) {}

void JpegEncoder::set_quality(int quality) {
    if (quality < 0) {
        quality_ = 0;
    } else if (quality > 100) {
        quality_ = 100;
    } else {
        quality_ = quality;
    }
}

bool JpegEncoder::encode(const cv::Mat& image, std::vector<uint8_t>& buffer) const {
    if (image.empty()) {
        return false;
    }
    std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, quality_};
    return cv::imencode(".jpg", image, buffer, params);
}

}  // namespace cansat
