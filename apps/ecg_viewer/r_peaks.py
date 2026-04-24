"""
This module implements algorithms to detect R-peaks, and filter RR intervals
before performing HRV analysis.
"""

import matplotlib.pyplot as plt
import numpy as np
import scipy
from neurokit2.signal.signal_smooth import signal_smooth
from numpy.typing import ArrayLike


def findpeaks_neurokit_mod(
    signal: ArrayLike,
    sampling_rate: float = 1000,
    smoothwindow: float = 0.1,
    avgwindow: float = 0.75,
    gradthreshweight: float = 1.5,
    minlenweight: float = 0.4,
    mindelay: float = 0.2,
    rel_sharpness_thresh=0.7,
    use_prominence: bool = True,
    compute_inverted: bool = False,
    show: bool = False,
) -> tuple[np.ndarray, list]:
    """
    Modified version of the neurokit ECG R peaks detection algorithm, which
    uses smoothed gradient thresholding to identify peaks.

    Additions are:
        * keeping only the higher amplitude peak when multiple detections are
          closer than the minimum delay (instead of keeping the first one)
        * computing and returning the "sharpness" of each detected event, defined
          as the ratio between the maximum gradient in the detected QRS segment
          to the maximum gradient threshold in that same region

    The "sharpness" can be later used to filter out misdetections by adapting
    the threshold to the local properties of the signal.

    Parameters
    ----------
    signal : ArrayLike
        The ECG signal to process
    sampling_rate : float, optional
        The sampling rate of the ECG, by default 1000
    smoothwindow : float, optional
        The size (in seconds) of the smoothing window to compute the gradient,
        by default 0.1
    avgwindow : float, optional
        The size (in seconds) of the averaging window to compute the gradient
        threshold, by default 0.75
    gradthreshweight : float, optional
        The relative gradient threshold with respect to the average, by default 1.5
    minlenweight : float, optional
        The threshold QRS segment width relative to the mean, by default 0.4
    mindelay : float, optional
        The minimum delay (in seconds) between two R peaks, by default 0.2
    rel_sharpness_thresh : float, optional
        The threshold on "sharpness" that is used to discriminate peaks detected
        within a mindelay duration. If no peak is significantly sharper than the
        other (using this threshold), then their amplitude is used to select which
        one to keep. By default, 0.7
    use_prominence : bool, optional
        If True, use the prominence of the local maxima to determine the peak location.
        If False, use the maximum of amplitude directly. By default, True
    compute_inverted: bool, optional
        If True, also find the peaks for the inverted signal (i.e., R peaks are
        negative).  Then the function returns two tuples, (peaks, sharpness) and
        (peaks_inv, sharpness_inv).  By default, False
    show : bool, optional
        Plot the result and gradients, by default False

    Returns
    -------
    ndarray, list
        A tuple containing the list of detected R peaks, and their "sharpness"
    """

    if show:
        __, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, sharex=True)

    # Compute the ECG's gradient as well as the gradient threshold. Run with
    # show=True in order to get an idea of the threshold.
    grad = np.gradient(signal)
    absgrad = np.abs(grad)
    smooth_kernel = int(np.rint(smoothwindow * sampling_rate))
    avg_kernel = int(np.rint(avgwindow * sampling_rate))
    smoothgrad = signal_smooth(absgrad, kernel="boxcar", size=smooth_kernel)
    avggrad = signal_smooth(smoothgrad, kernel="boxcar", size=avg_kernel)
    gradthreshold = gradthreshweight * avggrad
    mindelay = int(np.rint(sampling_rate * mindelay))

    if show:
        ax1.plot(signal)
        ax2.plot(smoothgrad)
        ax2.plot(gradthreshold)

    # Identify start and end of QRS complexes.
    qrs = smoothgrad > gradthreshold
    beg_qrs = np.where(np.logical_and(np.logical_not(qrs[0:-1]), qrs[1:]))[0]
    end_qrs = np.where(np.logical_and(qrs[0:-1], np.logical_not(qrs[1:])))[0]
    # Throw out QRS-ends that precede first QRS-start.
    end_qrs = end_qrs[end_qrs > beg_qrs[0]]

    # Identify R-peaks within QRS (ignore QRS that are too short).
    num_qrs = min(beg_qrs.size, end_qrs.size)
    min_len = np.mean(end_qrs[:num_qrs] - beg_qrs[:num_qrs]) * minlenweight

    peaks = [-2 * mindelay]
    sharpness = []
    last_amp = 0

    if compute_inverted:
        peaks_inv = [-2 * mindelay]
        sharpness_inv = []
        last_amp_inv = 0

    for i in range(num_qrs):
        beg = beg_qrs[i]
        end = end_qrs[i]
        len_qrs = end - beg

        if len_qrs < min_len:
            continue

        if show:
            ax2.axvspan(beg, end, facecolor="m", alpha=0.5)

        data = signal[beg:end]
        sharpness_ = np.max(smoothgrad[beg:end]) / np.max(gradthreshold[beg:end]) - 1

        # Find local maxima and their prominence within QRS.
        if use_prominence:
            # Identify most prominent local maximum.
            locmax, props = scipy.signal.find_peaks(data, prominence=(None, None))
            if locmax.size > 0:
                # Identify most prominent local maximum.
                prom_amax = np.argmax(props["prominences"])
                peak = beg + locmax[prom_amax]
                peak_amp = props["prominences"][prom_amax]
            else:
                peak = beg + np.argmax(data)
                peak_amp = signal[peak]

        # Use maximum of amplitude directly if not using prominence.
        else:
            peak = beg + np.argmax(data)
            peak_amp = signal[peak]

        ignore = False

        # Enforce minimum delay between peaks.
        if peak - peaks[-1] < mindelay:
            # Check if old peak is significantly sharper or if new peak is smaller and neither is sharper
            if sharpness_ / sharpness[-1] < rel_sharpness_thresh or (
                sharpness[-1] / sharpness_ > rel_sharpness_thresh
                and last_amp > peak_amp
            ):
                ignore = True
            # Else, discard the preceding one
            else:
                peaks.pop(-1)
                sharpness.pop(-1)

        if not ignore:
            sharpness.append(sharpness_)
            peaks.append(peak)
            last_amp = peak_amp

        # If compute_inverted is True, repeat the process for the inverted signal.
        if compute_inverted:
            if use_prominence:
                locmax, props = scipy.signal.find_peaks(-data, prominence=(None, None))
                if locmax.size > 0:
                    # Identify most prominent local maximum.
                    prom_amax = np.argmax(props["prominences"])
                    peak = beg + locmax[prom_amax]
                    peak_amp = props["prominences"][prom_amax]
                else:
                    peak = beg + np.argmax(-data)
                    peak_amp = -signal[peak]

            # Use maximum of amplitude directly if not using prominence.
            else:
                peak = beg + np.argmax(-data)
                peak_amp = -signal[peak]

            # Enforce minimum delay between peaks.
            if peak - peaks_inv[-1] < mindelay:
                # Check if old peak is significantly sharper or if new peak is smaller and neither is sharper
                if sharpness_ / sharpness_inv[-1] < rel_sharpness_thresh or (
                    sharpness_inv[-1] / sharpness_ > rel_sharpness_thresh
                    and last_amp_inv > peak_amp
                ):
                    continue
                # Else, discard the preceding one
                else:
                    peaks_inv.pop(-1)
                    sharpness_inv.pop(-1)

            sharpness_inv.append(sharpness_)
            peaks_inv.append(peak)
            last_amp_inv = peak_amp

    peaks.pop(0)
    peaks = np.asarray(peaks).astype(int)  # Convert to int

    if compute_inverted:
        peaks_inv.pop(0)
        peaks_inv = np.asarray(peaks_inv).astype(int)  # Convert to int

    if show:
        ax1.scatter(peaks, signal[peaks], c="r")
        if compute_inverted:
            ax1.scatter(peaks_inv, signal[peaks_inv], c="g")

    if compute_inverted:
        return (peaks, sharpness), (peaks_inv, sharpness_inv)

    return peaks, sharpness


def filter_sharpness(
    peaks: ArrayLike,
    lead: ArrayLike,
    sharpness: ArrayLike,
    rel_thresh: float = 0.7,
    abs_thresh: float = 0.5,
    uncertainty_margin: float = 0.1,
    amp_thresh: float = 0.6,
    show: bool = False,
) -> np.ndarray:
    """
    Filter R peaks to remove fake positives based on the local sharpness.

    Parameters
    ----------
    peaks : ArrayLike
        The R peaks to filter
    lead : ArrayLike
        The original ECG signal
    sharpness : ArrayLike
        The sharpness of each peak (as returned by findpeaks_neurokit_mod)
    rel_thresh : float, optional
        The relative sharpness to neighbours threshold, by default 0.7
    abs_thresh : float, optional
        The maximum absolute sharpness threshold, by default 0.5
    uncertainty_margin : float, optional
        The margin around threshold in which amplitude thresholding is also used,
        by default 0.1
    amp_thresh : float, optional
        The relative peak amplitude threshold, by default 0.6
    show : bool, optional
        Plot the sharpness and threshold, by default False

    Returns
    -------
    ndarray
        The filtered R peaks
    """

    # Compute the sharpness threshold compared to neighbours
    sharpness_thresh = np.min((sharpness[2:], sharpness[:-2]), axis=0) * rel_thresh
    sharpness_thresh = np.minimum(sharpness_thresh, abs_thresh)

    sharpness_delta = sharpness[1:-1] - sharpness_thresh

    # Exclude peaks with very low sharpness
    low_peaks = sharpness_delta < -uncertainty_margin

    # Identify peaks where sharpness is within uncertainty margin
    uncertain_peaks = np.logical_xor(sharpness_delta < 0, low_peaks)

    low_peaks = np.where(low_peaks)[0] + 1
    uncertain_peaks = np.where(uncertain_peaks)[0] + 1

    # For uncertain peaks, use relative amplitude to neighbours to discriminate
    neighbour_amps = np.min(
        (lead[peaks[uncertain_peaks - 1]], lead[peaks[uncertain_peaks + 1]]), axis=0
    )
    amps = lead[peaks[uncertain_peaks]]

    uncertain_peaks = uncertain_peaks[amps < neighbour_amps * amp_thresh]

    low_peaks = np.concatenate((low_peaks, uncertain_peaks))

    if show:
        __, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, sharex=True)
        ax1.plot(lead)
        ax1.scatter(peaks, lead[peaks], c="r")
        ax2.plot(peaks, sharpness)
        ax2.plot(peaks[1:-1], sharpness_thresh)

    # Filter out all detected wrong R peaks
    peaks = np.delete(peaks, low_peaks)

    if show:
        ax1.scatter(peaks, lead[peaks], c="g")

    return peaks


def findpeaks_ifch(
    signal: ArrayLike,
    sampling_rate: float = 1000,
    detect_inverted: bool = True,
    fastpeaks: bool = True,
    findpeaks_kwargs: dict = None,
    filter_kwargs: dict = None,
) -> np.ndarray:
    """
    R-peak detection algorithm based on local gradient thresholding and
    neighbourhood filtering.

    Parameters
    ----------
    signal : ArrayLike
        The ECG signal.
    sampling_rate : float, optional
        The sampling rate of the ECG, by default 1000
    detect_inverted : bool, optional
        If True, detect if the signal is inverted. By default, True
    fastpeaks : bool, optional
        If True, use the fast version of the peak detection algorithm, replacing
        prominence with amplitude. By default, True
    findpeaks_kwargs : dict, optional
        Additional keyword arguments passed to findpeaks_neurokit_mod, by default None
    filter_kwargs : dict, optional
        Additional keyword arguments passed to filter_sharpness, by default None

    Returns
    -------
    ndarray
        The detected R-peak positions
    """

    if findpeaks_kwargs is None:
        findpeaks_kwargs = {}
    if filter_kwargs is None:
        filter_kwargs = {}

    use_prominence = not fastpeaks
    findpeaks_kwargs["use_prominence"] = use_prominence
    findpeaks_kwargs["compute_inverted"] = detect_inverted

    if detect_inverted:
        result, result_inv = findpeaks_neurokit_mod(
            signal, sampling_rate, **findpeaks_kwargs
        )
        peaks, sharpness = result
        peaks_inv, sharpness_inv = result_inv

        is_inverted = np.median(signal[peaks]) < np.median(-signal[peaks_inv])

        if is_inverted:
            # If the signal is inverted, we return the inverted peaks
            peaks, sharpness = peaks_inv, sharpness_inv

    else:
        peaks, sharpness = findpeaks_neurokit_mod(
            signal, sampling_rate, **findpeaks_kwargs
        )

    peaks = filter_sharpness(peaks, signal, sharpness, **filter_kwargs)

    return peaks


def filter_rr_outliers(
    rr: ArrayLike,
    var_threshold: float = -0.25,
    avgsize: int = 9,
    trailing_average: bool = True,
    min_rr: float = 0.2,
    max_rr: int = 2,
    max_iter: int = 5,
    interpolation: str = "linear",
    filter_next: bool = False,
    in_place: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Filter RR intervals to remove outliers (e.g. extrasystoles, skipped beats).
    This is based on thresholding the RR variation with respect to an average
    computed over a neighbourhood. Detected outliers are then replaced with
    interpolated values.

    Parameters
    ----------
    rr : ArrayLike
        The RR intervals to filter
    var_threshold : float, optional
        The relative variation threshold to detect outliers, by default -0.25.
        If negative, will detect accelerations (extrasystoles). If positive,
        will detect decelerations (skipped beats).
    avgsize : int, optional
        The size of the averaging window, by default 9
    trailing_average : bool, optional
        Use a trailing window for the average (i.e. compare to preceding beats),
        by default True. If False, uses a centered averaging window.
    min_rr : float, optional
        The minimum acceptable RR interval (in seconds) after interpolation, by
        default 0.2. Set to None to disable this limit
    max_rr : float, optional
        The maximum acceptable RR interval (in seconds) after interpolation, by
        default 2. Set to None to disable this limit
    max_iter : int, optional
        Maximum number of repeated iterations, by default 5
    interpolation : str, optional
        Interpolation used to replace outliers, by default "linear".
        Can be either "cubic" or "linear". "cubic" uses the modified Akima method.
    filter_next : bool, optional
        Filter the beat right after the outlier RR too, by default False
        This is motivated by the fact that an ectopic beat can influence both
        the preceding RR and the following one.
    in_place : bool, optional
        Modify the input RR array directly, by default False

    Returns
    -------
    ndarray, ndarray
        The filtered RR intervals, and the mask of all detected outliers

    Raises
    ------
    NotImplementedError
        When an incorrect interpolation type is asked
    """

    if not in_place:
        rr = np.copy(rr)

    avgsize += 1

    if trailing_average:
        origin = (avgsize - 1) // 2
    else:
        origin = 0

    all_outliers = np.full(rr.shape, False, dtype=bool)

    for _ in range(max_iter):
        rr_mean = scipy.ndimage.uniform_filter1d(
            rr, avgsize, mode="mirror", origin=origin
        )
        rr_mean = ((rr_mean * avgsize) - rr) / (avgsize - 1)

        rr_var = (rr - rr_mean) / rr_mean

        if var_threshold < 0:
            outliers = rr_var < var_threshold
        else:
            outliers = rr_var > var_threshold

        if outliers.sum() == 0:
            break

        all_outliers |= outliers

        if filter_next:
            outliers[1:] |= outliers[:-1]

        x_out = outliers.nonzero()[0]
        x_vals = (~outliers).nonzero()[0]
        y_vals = rr[~outliers]

        if interpolation == "cubic":
            interp = scipy.interpolate.Akima1DInterpolator(
                x_vals, y_vals, method="makima", extrapolate=True
            )
            rr[outliers] = interp(x_out)
        elif interpolation == "linear":
            rr[outliers] = np.interp(x_out, x_vals, y_vals)
        else:
            raise NotImplementedError(f"Interpolation not known : {interpolation}")

        if min_rr is not None:
            rr = np.maximum(rr, min_rr)
        if max_rr is not None:
            rr = np.minimum(rr, max_rr)

    return rr, all_outliers


def filter_rr_complete(
    rr: ArrayLike,
    var_threshold: float = 0.25,
    max_iter: int = 5,
    interpolation: str = "linear",
    filter_next: bool = False,
    in_place: bool = False,
    accel_kwargs: dict = None,
    decel_kwargs: dict = None,
) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
    """
    Filters the RR intervals using local thresholding. Uses 2 consecutive passes:
    1. remove the extrasystoles and abnormally fast beats
    2. remove the skipped beats and abnormally slow beats

    Parameters
    ----------
    rr : ArrayLike
        The RR intervals to filter
    var_threshold : float, optional
        The relative variation threshold to detect outliers, by default -0.25.
    max_iter : int, optional
        Maximum number of repeated iterations, by default 5
    interpolation : str, optional
        Interpolation used to replace outliers, by default "linear".
        Can be either "cubic" or "linear". "cubic" uses the modified Akima method.
    filter_next : bool, optional
        Filter the beat right after the outlier RR too, by default False
        This is motivated by the fact that an ectopic beat can influence both
        the preceding RR and the following one.
    in_place : bool, optional
        Modify the input RR array directly, by default False
    accel_kwargs : _type_, optional
        Additional parameters passed to filter_rr_outliers for acceleration
        detection, by default None
    decel_kwargs : _type_, optional
        Additional parameters passed to filter_rr_outliers for deceleration
        detection, by default None

    Returns
    -------
    ndarray, (ndarray, ndarray)
        The filtered RR intervals, and the masks of faster and slower detected outliers
    """

    if accel_kwargs is None:
        accel_kwargs = {
            "avgsize": 15,
            "trailing_average": True,
        }

    if decel_kwargs is None:
        decel_kwargs = {
            "avgsize": 5,
            "trailing_average": False,
        }

    rr, accel_mask = filter_rr_outliers(
        rr,
        -var_threshold,
        max_iter=max_iter,
        interpolation=interpolation,
        filter_next=filter_next,
        in_place=in_place,
        **accel_kwargs,
    )

    rr, decel_mask = filter_rr_outliers(
        rr,
        var_threshold,
        max_iter=max_iter,
        interpolation=interpolation,
        filter_next=filter_next,
        in_place=in_place,
        **decel_kwargs,
    )

    return rr, (accel_mask, decel_mask)
