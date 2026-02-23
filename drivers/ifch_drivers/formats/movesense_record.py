import enum
import logging
import pathlib

import h5py
import numpy as np

from ifch_drivers import __version__

FORMAT_TAG = f"ifch_movesense_record-{__version__}"


class MovesenseDataTypes(enum.Enum):
    scale: float

    def __new__(cls, title: str, scale: float = 1):
        obj = object.__new__(cls)
        obj._value_ = title

        obj.scale = scale
        return obj

    ECG = "/Meas/ECG".upper(), 0.38147e-6
    ECGMV = "/Meas/ECG/mv".upper(), 1e-3
    IMU6 = "/Meas/IMU6".upper()
    IMU9 = "/Meas/IMU9".upper()
    ACC = "/Meas/Acc".upper()
    GYRO = "/Meas/Gyro".upper()
    MAGN = "/Meas/Magn".upper()
    UTCTIME = "/Time/Detailed".upper(), 1e-6

    @classmethod
    def from_path(cls, path):
        split_path = path.split("/")

        if len(split_path) > 3:
            sampling = int(split_path.pop(3))
        else:
            sampling = 0

        data_type = "/".join(split_path)
        data_type = cls(data_type.upper())

        return data_type, sampling


def write(
    file_path: pathlib.Path | str,
    record: dict,
    metadata: dict = {},
    sensor_paths: list = [],
):
    """
    Write a Movesense record to an HDF5 file.
    The provided metadata will be stored as attributes of the root group.

    Args:
        file_path (pathlib.Path | str): where to write the HDF5 file
        record (dict): the Movesense record to write, in dict format
        metadata (dict, optional): the metadata to write as attributes
        sensor_paths (list, optional): list of sensor paths included in the record
            (this will be used to extract sampling and scale information for each sensor)
    Raises:
        ValueError: if the provided sensor_paths do not match sensors in the record
    """

    sensor_properties = {}

    # Store sampling and scale for each sensor in sensor_paths
    for sensor in sensor_paths:
        sensor_name, sampling = MovesenseDataTypes.from_path(sensor)

        if sensor_name.name not in record:
            logging.warning(
                f"Sensor {sensor_name.name} provided in sensor_paths not found in record, discarding"
            )
        else:
            sensor_properties[sensor_name.name] = {
                "sampling": sampling,
                "scale": sensor_name.scale,
            }
    for sensor_name in record.keys():
        if sensor_name not in sensor_properties:
            logging.warning(
                f"Sensor {sensor_name} found in record but not provided in sensor_paths, flagging invalid properties"
            )
            sensor_properties[sensor_name] = {
                "sampling": -1,
                "scale": -1,
            }

    if not isinstance(file_path, pathlib.Path):
        file_path = pathlib.Path(file_path)

    # Ensure that the extension is .h5
    if file_path.suffix != ".h5":
        file_path = file_path.with_suffix(".h5")

    with h5py.File(file_path, "w") as hfile:
        # Create a group for each sensor in the record
        for sensor_name, sensor_dict in record.items():
            sensor_group = hfile.create_group(sensor_name)

            # Store the data for this sensor as datasets in the sensor group
            for key, data in sensor_dict.items():
                data = np.asarray(data)
                sensor_group.create_dataset(key, data=data, compression="gzip")

        for sensor, properties in sensor_properties.items():
            sensor_group = hfile[sensor]
            for key, value in properties.items():
                sensor_group.attrs[key] = value

        def add_attr(group, key, value):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    composed_key = f"{key}.{sub_key}"
                    add_attr(group, composed_key, sub_value)
            else:
                group.attrs[key] = value

        if "format" in metadata:
            raise ValueError("'format' is a reserved metadata key and cannot be used.")
        metadata["format"] = FORMAT_TAG

        # Store the metadata as attributes of the root group
        for key, value in metadata.items():
            add_attr(hfile, key, value)


def load(file_path: pathlib.Path | str, flatten=True) -> tuple[dict, dict, dict]:
    """
    Read a Movesense record from an HDF5 file.

    Args:
        file_path (pathlib.Path | str): path to the HDF5 file to read
        flatten (bool, optional): if True, the timestamps and samples will be
            flattened to have one timestamp per sample. Defaults to True.
    Returns:
        tuple: (record, metadata, properties)
            record (dict): the Movesense record in dict format
            metadata (dict): the metadata of the record
            properties (dict): the properties of each sensor
    """

    if not isinstance(file_path, pathlib.Path):
        file_path = pathlib.Path(file_path)

    record = {}
    properties = {}

    with h5py.File(file_path, "r") as hfile:
        metadata = dict(hfile.attrs)

        for sensor_name in hfile.keys():
            sensor_group = hfile[sensor_name]
            sensor_dict = {}
            for key in sensor_group.keys():
                sensor_dict[key] = sensor_group[key][:]
            record[sensor_name] = sensor_dict

            properties[sensor_name] = dict(sensor_group.attrs)

    keys = list(metadata.keys())

    for key in keys:
        if "." in key:
            parts = key.split(".")
            current_level = metadata
            for part in parts[:-1]:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]
            current_level[parts[-1]] = metadata[key]

            del metadata[key]

    if flatten:
        for sensor_name, sensor_dict in record.items():
            n_samples = -1
            for key, samples in sensor_dict.items():
                if key == "timestamps":
                    continue

                n_samples = samples.shape[1]
                samples = np.concatenate(samples, axis=0)
                sensor_dict[key] = samples

            timestamps = sensor_dict["timestamps"]
            delta_t = np.diff(timestamps)
            delta_t = np.append(delta_t, delta_t[-1])

            delta_t = (
                delta_t.reshape(-1, 1) / n_samples * np.arange(n_samples).reshape(1, -1)
            )

            timestamps = (timestamps.reshape(-1, 1) + delta_t).flatten()

            sensor_dict["timestamps"] = timestamps

    return record, metadata, properties
