#include "capture.hpp"
#include "encoding.hpp"

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include <opencv2/imgproc.hpp>

namespace {

using Clock = std::chrono::steady_clock;

struct Options {
    int device_id = 0;
    int input_width = 2560;
    int input_height = 720;
    int fps = 30;
    int output_width = 256;
    int output_height = 144;
    int jpeg_quality = 45;
    std::string output_path;
};

void print_usage() {
    std::cout
        << "Uso: cansat_image_tool --output <path> [opciones]\n"
        << "Opciones:\n"
        << "  --device-id <int>\n"
        << "  --input-width <int>\n"
        << "  --input-height <int>\n"
        << "  --fps <int>\n"
        << "  --output-width <int>\n"
        << "  --output-height <int>\n"
        << "  --jpeg-quality <0-100>\n";
}

int parse_int_arg(char* value) {
    return std::stoi(value);
}

Options parse_args(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--output" && i + 1 < argc) {
            options.output_path = argv[++i];
        } else if (arg == "--device-id" && i + 1 < argc) {
            options.device_id = parse_int_arg(argv[++i]);
        } else if (arg == "--input-width" && i + 1 < argc) {
            options.input_width = parse_int_arg(argv[++i]);
        } else if (arg == "--input-height" && i + 1 < argc) {
            options.input_height = parse_int_arg(argv[++i]);
        } else if (arg == "--fps" && i + 1 < argc) {
            options.fps = parse_int_arg(argv[++i]);
        } else if (arg == "--output-width" && i + 1 < argc) {
            options.output_width = parse_int_arg(argv[++i]);
        } else if (arg == "--output-height" && i + 1 < argc) {
            options.output_height = parse_int_arg(argv[++i]);
        } else if (arg == "--jpeg-quality" && i + 1 < argc) {
            options.jpeg_quality = parse_int_arg(argv[++i]);
        } else {
            throw std::runtime_error("Argumento invalido: " + arg);
        }
    }

    if (options.output_path.empty()) {
        throw std::runtime_error("Falta --output <path>");
    }

    if (options.input_width <= 0 || options.input_height <= 0 || options.output_width <= 0 || options.output_height <= 0) {
        throw std::runtime_error("Dimensiones invalidas");
    }

    return options;
}

cv::Mat build_anaglyph_transposed(const cv::Mat& left, const cv::Mat& right) {
    if (left.empty() || right.empty()) {
        return cv::Mat();
    }
    if (left.rows != right.rows || left.cols != right.cols || left.type() != CV_8UC3 || right.type() != CV_8UC3) {
        return cv::Mat();
    }

    const int src_rows = left.rows;
    const int src_cols = left.cols;

    cv::Mat out(src_cols, src_rows, CV_8UC3);

    for (int r = 0; r < src_rows; ++r) {
        const cv::Vec3b* left_row = left.ptr<cv::Vec3b>(r);
        const cv::Vec3b* right_row = right.ptr<cv::Vec3b>(r);
        for (int c = 0; c < src_cols; ++c) {
            const cv::Vec3b& lpx = left_row[c];
            const cv::Vec3b& rpx = right_row[c];

            cv::Vec3b& dst = out.at<cv::Vec3b>(c, r);
            dst[2] = lpx[2];  // R del ojo izquierdo
            dst[1] = rpx[1];  // G del ojo derecho
            dst[0] = rpx[0];  // B del ojo derecho
        }
    }

    return out;
}

bool write_binary_file(const std::string& path, const std::vector<uint8_t>& data) {
    std::ofstream ofs(path, std::ios::binary);
    if (!ofs.is_open()) {
        return false;
    }
    ofs.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    return ofs.good();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto t0 = Clock::now();
        const Options options = parse_args(argc, argv);

        const auto t_capture_start = Clock::now();
        cansat::CameraCapture camera(options.device_id, options.input_width, options.input_height, options.fps);
        camera.open();

        cv::Mat frame;
        if (!camera.grab_frame(frame)) {
            throw std::runtime_error("No se pudo capturar frame");
        }
        camera.release();
        const auto t_capture_end = Clock::now();

        if (frame.cols < 2) {
            throw std::runtime_error("Frame invalido para side-by-side");
        }

        const int half_width = frame.cols / 2;
        cv::Rect left_roi(0, 0, half_width, frame.rows);
        cv::Rect right_roi(half_width, 0, half_width, frame.rows);

        cv::Mat left = frame(left_roi).clone();
        cv::Mat right = frame(right_roi).clone();

        cv::Mat left_resized;
        cv::Mat right_resized;
        cv::resize(left, left_resized, cv::Size(options.output_width, options.output_height));
        cv::resize(right, right_resized, cv::Size(options.output_width, options.output_height));

        const auto t_process_start = Clock::now();
        cv::Mat anaglyph = build_anaglyph_transposed(left_resized, right_resized);
        if (anaglyph.empty()) {
            throw std::runtime_error("Fallo al generar anaglifo");
        }
        const auto t_process_end = Clock::now();

        cansat::JpegEncoder encoder(options.jpeg_quality);
        std::vector<uint8_t> jpeg_bytes;
        if (!encoder.encode(anaglyph, jpeg_bytes)) {
            throw std::runtime_error("Fallo al codificar JPEG");
        }

        if (!write_binary_file(options.output_path, jpeg_bytes)) {
            throw std::runtime_error("No se pudo guardar JPEG de salida");
        }

        const auto t1 = Clock::now();

        const auto capture_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_capture_end - t_capture_start).count();
        const auto process_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_process_end - t_process_start).count();
        const auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

        std::cout << "[cpp] captura_ms=" << capture_ms
                  << " process_ms=" << process_ms
                  << " total_ms=" << total_ms
                  << " output=" << options.output_path
                  << " bytes=" << jpeg_bytes.size() << std::endl;

        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "[cpp][error] " << exc.what() << std::endl;
        print_usage();
        return 1;
    }
}
