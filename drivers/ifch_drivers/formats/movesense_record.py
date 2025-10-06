import pathlib

import h5py
import numpy as np


def write(file_path: pathlib.Path | str, record: dict, metadata: dict):
    """
    Write a Movesense record to an HDF5 file.
    The provided metadata will be stored as attributes of the root group, except
    for keys corresponding to sensors in the record, which will be stored as attributes
    of the corresponding sensor group.

    Args:
        file_path (pathlib.Path | str): where to write the HDF5 file
        record (dict): the Movesense record to write, in dict format
        metadata (dict): the metadata to write as attributes
    """

    if not isinstance(file_path, pathlib.Path):
        file_path = pathlib.Path(file_path)

    # Ensure that the extension is .h5
    if file_path.suffix != ".h5":
        file_path = file_path.with_suffix(".h5")

    with h5py.File(file_path, "w") as hfile:
        # Create a group for each sensor in the record
        for sensor_name, sensor_dict in record.items():
            sensor_group = hfile.create_group(sensor_name)

            # Store metadata for this sensor as attributes of the sensor group
            if sensor_name in metadata:
                for key, value in metadata[sensor_name].items():
                    sensor_group.attrs[key] = value
                metadata.pop(sensor_name)

            # Store the data for this sensor as datasets in the sensor group
            for key, data in sensor_dict.items():
                data = np.asarray(data)
                sensor_group.create_dataset(key, data=data, compression="gzip")

        # Store the remaining metadata as attributes of the root group
        for key, value in metadata.items():
            hfile.attrs[key] = value
