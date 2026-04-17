from __future__ import annotations

import logging
import math
import os
import time

try:
    import smbus2 as smbus
except Exception:
    smbus = None

try:
    import board
    import busio
except Exception:
    board = None
    busio = None

try:
    import adafruit_mmc56x3
except Exception:
    adafruit_mmc56x3 = None

try:
    import adafruit_bme280.basic as adafruit_bme280
except Exception:
    adafruit_bme280 = None

CMD_CONVERT_D1 = 0x48
CMD_CONVERT_D2 = 0x50

BMI160_REG_CMD = 0x7E
BMI160_CMD_ACC_NORMAL = 0x11
BMI160_CMD_GYR_NORMAL = 0x15
BMI160_REG_ACC_RANGE = 0x41
BMI160_REG_GYR_RANGE = 0x43

G_TO_MS2 = 9.80665


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("context.sensors")


def signed_16(lsb: int, msb: int) -> int:
    value = (msb << 8) | lsb
    if value >= 0x8000:
        value -= 0x10000
    return value


def ms5611_reset(bus, addr: int) -> None:
    bus.write_byte(addr, 0x1E)
    time.sleep(0.01)


def ms5611_read_prom(bus, addr: int) -> list[int]:
    coeffs = []
    for i in range(8):
        data = bus.read_i2c_block_data(addr, 0xA0 + (i * 2), 2)
        coeffs.append((data[0] << 8) | data[1])
    return coeffs


def ms5611_read_adc(bus, addr: int, cmd: int) -> int:
    bus.write_byte(addr, cmd)
    time.sleep(0.01)
    data = bus.read_i2c_block_data(addr, 0x00, 3)
    return (data[0] << 16) | (data[1] << 8) | data[2]


def ms5611_calculate(d1: int, d2: int, coeffs: list[int]) -> tuple[float, float]:
    d_t = d2 - coeffs[5] * 256
    temp = 2000 + d_t * coeffs[6] / 8388608
    off = coeffs[2] * 65536 + (coeffs[4] * d_t) / 128
    sens = coeffs[1] * 32768 + (coeffs[3] * d_t) / 256
    pressure = (d1 * sens / 2097152 - off) / 32768
    return temp / 100.0, pressure / 100.0


def pressure_to_altitude(pressure_hpa: float, sea_level_hpa: float = 1013.25) -> float:
    if pressure_hpa <= 0:
        return 0.0
    return 44330.0 * (1.0 - math.pow(pressure_hpa / sea_level_hpa, 1.0 / 5.255))


def read_ina226(bus, addr: int, r_shunt_ohm: float) -> tuple[float, float, float]:
    data_v = bus.read_i2c_block_data(addr, 0x02, 2)
    raw_v = (data_v[0] << 8) | data_v[1]
    voltage_v = raw_v * 0.00125

    data_s = bus.read_i2c_block_data(addr, 0x01, 2)
    raw_s = (data_s[0] << 8) | data_s[1]
    if raw_s > 32767:
        raw_s -= 65536

    shunt_v = raw_s * 0.0000025
    current_a = shunt_v / r_shunt_ohm
    current_ma = current_a * 1000.0
    power_mw = voltage_v * current_ma
    return voltage_v, current_ma, power_mw


def init_bmi160(bus, addr: int) -> None:
    bus.write_byte_data(addr, BMI160_REG_CMD, BMI160_CMD_ACC_NORMAL)
    time.sleep(0.05)
    bus.write_byte_data(addr, BMI160_REG_CMD, BMI160_CMD_GYR_NORMAL)
    time.sleep(0.05)
    bus.write_byte_data(addr, BMI160_REG_ACC_RANGE, 0x03)
    bus.write_byte_data(addr, BMI160_REG_GYR_RANGE, 0x00)


def read_bmi160(bus, addr: int) -> tuple[float, float, float, float]:
    raw = bus.read_i2c_block_data(addr, 0x0C, 12)
    gyro_z_raw = signed_16(raw[4], raw[5])
    acc_x_raw = signed_16(raw[6], raw[7])
    acc_y_raw = signed_16(raw[8], raw[9])
    acc_z_raw = signed_16(raw[10], raw[11])

    gyro_z_dps = gyro_z_raw / 16.4
    acc_x = (acc_x_raw / 16384.0) * G_TO_MS2
    acc_y = (acc_y_raw / 16384.0) * G_TO_MS2
    acc_z = (acc_z_raw / 16384.0) * G_TO_MS2
    return acc_x, acc_y, acc_z, gyro_z_dps


def main() -> None:
    logger = setup_logging()

    ms5611_addr = int(os.getenv("MS5611_ADDR", "0x77"), 0)
    ina226_addr = int(os.getenv("INA226_ADDR", "0x40"), 0)
    bmi160_addr = int(os.getenv("BMI160_ADDR", "0x69"), 0)
    bme280_addr = int(os.getenv("BME280_ADDR", "0x76"), 0)
    r_shunt = float(os.getenv("INA226_R_SHUNT", "0.1"))
    sleep_s = float(os.getenv("SENSORS_POLL_INTERVAL_S", "1.5"))
    sea_level_hpa = float(os.getenv("SEA_LEVEL_PRESSURE_HPA", "1013.25"))

    logger.info("Inicializando sensores finales: MS5611, MMC56x3, INA226, BMI160, BME280")

    bus = None
    i2c = None
    mmc_sensor = None
    bme_sensor = None
    ms_coeffs = None
    bmi_ready = False

    if smbus is None:
        logger.warning("smbus2 no instalado. MS5611/INA226/BMI160 quedaran en 0")
    else:
        try:
            bus = smbus.SMBus(1)
        except Exception as exc:
            logger.warning("No se pudo abrir SMBus(1): %s", exc)

    if board is None or busio is None:
        logger.warning("board/busio no instalado. MMC56x3/BME280 quedaran en 0")
    else:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
        except Exception as exc:
            logger.warning("No se pudo inicializar I2C board: %s", exc)

    if bus is not None:
        try:
            ms5611_reset(bus, ms5611_addr)
            ms_coeffs = ms5611_read_prom(bus, ms5611_addr)
            logger.info("MS5611 detectado")
        except Exception as exc:
            logger.warning("MS5611 ausente: %s", exc)

        try:
            _ = read_ina226(bus, ina226_addr, r_shunt)
            logger.info("INA226 detectado")
        except Exception as exc:
            logger.warning("INA226 ausente: %s", exc)

        try:
            init_bmi160(bus, bmi160_addr)
            bmi_ready = True
            logger.info("BMI160 detectado")
        except Exception as exc:
            logger.warning("BMI160 ausente: %s", exc)

    if i2c is not None and adafruit_mmc56x3 is not None:
        try:
            mmc_sensor = adafruit_mmc56x3.MMC5603(i2c)
            logger.info("MMC56x3 detectado")
        except Exception as exc:
            logger.warning("MMC56x3 ausente: %s", exc)
    else:
        logger.warning("Libreria adafruit_mmc56x3 ausente. MMC56x3 quedara en 0")

    if i2c is not None and adafruit_bme280 is not None:
        try:
            bme_sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=bme280_addr)
            bme_sensor.sea_level_pressure = sea_level_hpa
            logger.info("BME280 detectado")
        except Exception as exc:
            logger.warning("BME280 ausente: %s", exc)
    else:
        logger.warning("Libreria adafruit_bme280 ausente. BME280 quedara en 0")

    try:
        while True:
            payload = {
                "time": int(time.time() * 1000),
                "alt_ms5611": 0.0,
                "alt_bme280": 0.0,
                "pressure": 0.0,
                "temperature": 0.0,
                "velocity_z": 0.0,
                "accel_x": 0.0,
                "accel_y": 0.0,
                "accel_z": 0.0,
                "gyro_z": 0.0,
                "voltage": 0.0,
                "current": 0.0,
            }

            if mmc_sensor is not None:
                try:
                    mag_x, mag_y, mag_z = mmc_sensor.magnetic
                except Exception:
                    mag_x, mag_y, mag_z = 0.0, 0.0, 0.0
            else:
                mag_x, mag_y, mag_z = 0.0, 0.0, 0.0

            if bus is not None and ms_coeffs is not None:
                try:
                    d1 = ms5611_read_adc(bus, ms5611_addr, CMD_CONVERT_D1)
                    d2 = ms5611_read_adc(bus, ms5611_addr, CMD_CONVERT_D2)
                    temp_c, pressure_hpa = ms5611_calculate(d1, d2, ms_coeffs)
                    payload["temperature"] = float(temp_c)
                    payload["pressure"] = float(pressure_hpa)
                    payload["alt_ms5611"] = pressure_to_altitude(pressure_hpa, sea_level_hpa)
                except Exception:
                    pass

            if bme_sensor is not None:
                try:
                    payload["temperature"] = float(bme_sensor.temperature)
                    payload["pressure"] = float(bme_sensor.pressure)
                    payload["alt_bme280"] = float(getattr(bme_sensor, "altitude", 0.0))
                except Exception:
                    pass

            if bus is not None and bmi_ready:
                try:
                    acc_x, acc_y, acc_z, gyro_z = read_bmi160(bus, bmi160_addr)
                    payload["accel_x"] = float(acc_x)
                    payload["accel_y"] = float(acc_y)
                    payload["accel_z"] = float(acc_z)
                    payload["gyro_z"] = float(gyro_z)
                except Exception:
                    pass

            if bus is not None:
                try:
                    voltage, current_ma, _power_mw = read_ina226(bus, ina226_addr, r_shunt)
                    payload["voltage"] = float(voltage)
                    payload["current"] = float(current_ma)
                except Exception:
                    pass

            print("============== LECTURA EN VIVO ==============")
            print(f"Time ms     -> {payload['time']}")
            print(f"MS5611      -> Alt: {payload['alt_ms5611']:.2f} m | Pres: {payload['pressure']:.2f} hPa")
            print(f"BME280      -> Alt: {payload['alt_bme280']:.2f} m | Temp: {payload['temperature']:.2f} C")
            print(
                f"BMI160      -> Acc(m/s2): X={payload['accel_x']:.2f} Y={payload['accel_y']:.2f} Z={payload['accel_z']:.2f} | GyroZ={payload['gyro_z']:.2f}"
            )
            print(f"INA226      -> Volt: {payload['voltage']:.2f} V | Corriente: {payload['current']:.2f} mA")
            print(f"MMC56x3     -> X: {mag_x:.2f} | Y: {mag_y:.2f} | Z: {mag_z:.2f} uT")
            print("=============================================\n")

            time.sleep(sleep_s)

    except KeyboardInterrupt:
        logger.info("Lectura detenida por el usuario")
    finally:
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass
        if i2c is not None:
            try:
                i2c.deinit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
