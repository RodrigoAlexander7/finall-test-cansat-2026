#pragma once

#include <cstdint>
#include <opencv2/core.hpp>
#include <vector>

namespace cansat {

class JpegEncoder {
public:
    explicit JpegEncoder(int quality);
    void set_quality(int quality);
    bool encode(const cv::Mat& image, std::vector<uint8_t>& buffer) const;

private:
    int quality_;
};

}  // namespace cansat
