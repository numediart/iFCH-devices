import pathlib

import h5py
import numpy as np

from .movesense_stream import MovesenseDataTypes


def write(
    file_path: pathlib.Path | str, record: dict, metadata: dict, sensor_paths: list
):
    """
    Write a Movesense record to an HDF5 file.
    The provided metadata will be stored as attributes of the root group.

    Args:
        file_path (pathlib.Path | str): where to write the HDF5 file
        record (dict): the Movesense record to write, in dict format
        metadata (dict): the metadata to write as attributes
        sensor_paths (list): list of sensor paths included in the record
    """

    if len(sensor_paths) != len(record):
        raise ValueError("Mismatch between sensor_paths and record keys")

    sensor_properties = {}

    # Store sampling and scale for each sensor in sensor_paths
    for sensor in sensor_paths:
        sensor_name, sampling = MovesenseDataTypes.from_path(sensor)

        scale = 1
        if sensor_name == MovesenseDataTypes.ECG:
            scale = 0.38147e-6
        elif sensor_name == MovesenseDataTypes.ECGMV:
            scale = 1e-3

        if sensor_name.name not in record:
            raise ValueError(f"Sensor {sensor_name.name} not found in record")
        else:
            sensor_properties[sensor_name.name] = {
                "sampling": sampling,
                "scale": scale,
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

            for key, value in sensor_properties[sensor_name].items():
                sensor_group.attrs[key] = value

        def add_attr(group, key, value):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    composed_key = f"{key}.{sub_key}"
                    add_attr(group, composed_key, sub_value)
            else:
                group.attrs[key] = value

        # Store the metadata as attributes of the root group
        for key, value in metadata.items():
            add_attr(hfile, key, value)
