#!/usr/bin/python

import sys
import os
import gpxpy
import datetime
import pyexiv2
import math
import time
from pyexiv2.utils import make_fraction
from dateutil.tz import tzlocal
from lib.geo import interpolate_lat_lon, decimal_to_dms, utc_to_localtime

'''
Script for geotagging images using a gpx file from an external GPS.
Intended as a lightweight tool.

!!! This version needs testing, please report issues.!!!

Uses the capture time in EXIF and looks up an interpolated lat, lon, bearing
for each image, and writes the values to the EXIF of the image.

You can supply a time offset in seconds if the GPS clock and camera clocks are not in sync.

Requires gpxpy, e.g. 'pip install gpxpy'

Requires pyexiv2, see install instructions at http://tilloy.net/dev/pyexiv2/
(or use your favorite installer, e.g. 'brew install pyexiv2').
'''


def get_lat_lon_time(gpx_file, use_localtime=True):
    '''
    Read location and time stamps from a track in a GPX file.

    Returns a list of tuples (time, lat, lon).

    GPX stores time in UTC, assume your camera used the local
    timezone and convert accordingly.

    Args:
    use_localtime(boolean): conver GPX timestamps into localtime
    '''
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)

    points = []
    if len(gpx.tracks)>0:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if use_localtime:
                        points.append(((utc_to_localtime(point.time), point.latitude, point.longitude, point.elevation)))
                    else:
                        points.append((point.time, point.latitude, point.longitude, point.elevation))
    if len(gpx.waypoints) > 0:
        for point in gpx.waypoints:
            if use_localtime:
                points.append(((utc_to_localtime(point.time), point.latitude, point.longitude, point.elevation)))
            else:
                points.append((point.time, point.latitude, point.longitude, point.elevation))

    # sort by time just in case
    points.sort()

    return points


def add_bearing_offset(bearing, offset):
    '''
    Add offset to bearing and ensure that the result r is 0 <= r < 360.
    '''
    r = bearing + offset
    if r >= 0 and r < 360:
        return r
    if r >= 360:
        return r % 360
    return -(-r % 360)


def add_exif_using_timestamp(filename, time, points, offset_time=0, bearing_offset=0.0, verbose=False):
    '''
    Find lat, lon and bearing of filename and write to EXIF.
    '''

    metadata = pyexiv2.ImageMetadata(filename)
    metadata.read()

    # subtract offset in s beween gpx time and exif time
    t = time - datetime.timedelta(seconds=offset_time)

    try:
        lat, lon, bearing, elevation = interpolate_lat_lon(points, t)

        bearing = add_bearing_offset(bearing, bearing_offset)

        lat_deg = decimal_to_dms(lat, ["S", "N"])
        lon_deg = decimal_to_dms(lon, ["W", "E"])

        # convert decimal coordinates into degrees, minutes and seconds as fractions for EXIF
        exiv_lat = (make_fraction(lat_deg[0],1), make_fraction(int(lat_deg[1]),1), make_fraction(int(lat_deg[2]*1000000),1000000))
        exiv_lon = (make_fraction(lon_deg[0],1), make_fraction(int(lon_deg[1]),1), make_fraction(int(lon_deg[2]*1000000),1000000))

        # convert direction into fraction
        exiv_bearing = make_fraction(int(bearing*100),100)

        # add to exif
        metadata["Exif.GPSInfo.GPSLatitude"] = exiv_lat
        metadata["Exif.GPSInfo.GPSLatitudeRef"] = lat_deg[3]
        metadata["Exif.GPSInfo.GPSLongitude"] = exiv_lon
        metadata["Exif.GPSInfo.GPSLongitudeRef"] = lon_deg[3]
        metadata["Exif.Image.GPSTag"] = 654
        metadata["Exif.GPSInfo.GPSMapDatum"] = "WGS-84"
        metadata["Exif.GPSInfo.GPSVersionID"] = '2 0 0 0'
        metadata["Exif.GPSInfo.GPSImgDirection"] = exiv_bearing
        metadata["Exif.GPSInfo.GPSImgDirectionRef"] = "T"

        if elevation is not None:
            exiv_elevation = make_fraction(abs(int(elevation*10)),10)
            metadata["Exif.GPSInfo.GPSAltitude"] = exiv_elevation
            metadata["Exif.GPSInfo.GPSAltitudeRef"] = '0' if elevation >= 0 else '1'

        metadata.write()
        if verbose:
            print("Added geodata to: {}  time {}  lat {}  lon {}  alt {}  bearing {}".format(filename, time, lat, lon, elevation, bearing))
    except ValueError as e:
        print("Skipping {0}: {1}".format(filename, e))


def exif_time(filename):
    '''
    Get image capture time from exif
    '''
    m = pyexiv2.ImageMetadata(filename)
    m.read()
    image_millisec = 0
    try:
        image_time = m['Exif.Photo.DateTimeOriginal'].value
        image_millisec = int(m['Exif.Photo.SubSecTimeOriginal'].value)
    except ValueError as e:
        print("Error reading EXIF at {0}: {1}".format(filename, e))
    except KeyError as e: # thrown if "Exif.Photo.SubSecTimeOriginal" is not set
        print("Error reading {0}: {1}".format(filename, e))
    image_time = image_time + datetime.timedelta(milliseconds=int(image_millisec))
    return image_time


def estimate_sub_second_time(files, interval):
    '''
    Estimate the capture time of a sequence with sub-second precision

    EXIF times are only given up to a second of precission. This function
    uses the given interval between shots to Estimate the time inside that
    second that each picture was taken.
    '''
    if interval <= 0.0:
        return [exif_time(f) for f in files]

    onesecond = datetime.timedelta(seconds=1.0)
    T = datetime.timedelta(seconds=interval)
    for i, f in enumerate(files):
        m = exif_time(f)
        if i == 0:
            smin = m
            smax = m + onesecond
        else:
            m0 = m - T * i
            smin = max(smin, m0)
            smax = min(smax, m0 + onesecond)

    if smin > smax:
        print('Interval not compatible with EXIF times')
        return None
    else:
        s = smin + (smax - smin) / 2
        return [s + T * i for i in range(len(files))]


def is_interesting(directory, fname):
    p1, p2 = os.path.splitext(fname)
    if p2.lower() == '.jpg' and os.path.isfile(os.path.join(directory, fname)):
        return True
    return False


def get_args():
    import argparse
    p = argparse.ArgumentParser(description='Geotag one or more photos with location and orientation from GPX file.')
    p.add_argument('path', help='Path containing JPG files, or location of one JPG file.')
    p.add_argument('gpx_file', help='Location of GPX file to get locations from.')
    p.add_argument('--time-offset',
        help='Time offset between GPX and photos. If your camera is ahead by one minute, time_offset is 60.',
        default=0, type=float)
    p.add_argument('--interval',
        help='Time between shots. Used to set images times with sub-second precission',
        type=float, default=0.0)
    p.add_argument('--localtime',
        help='Convert GPX timestamps into localtime, treat EXIF timestamps as timestamps in localtime. Localtime is the local timezone set on your computer, not the localtime at the place and time when you took the photo.',
        action='store_true')
    p.add_argument('-r', '--recurse',
         action='store_true',
         help='Work recursive on all subdirectories.')
    p.add_argument('-v', '--verbose',
        action='store_true',
        help='Verbose output')
    p.add_argument('-b', '--bearing-offset',
        type=float,
        default=0,
        help='Add offset in degree to bearing. For example, use 180.0 if you took your photos backwards.')
    return p.parse_args()


if __name__ == '__main__':
    args = get_args()

    now = datetime.datetime.now(tzlocal())
    if args.localtime:
        print("Your local timezone is {0}, if this is not correct, your geotags will be wrong.".format(now.strftime('%Y-%m-%d %H:%M:%S %Z')))

    print('Reading file list.')
    if args.path.lower().endswith(".jpg"):
        # single file
        file_list = [args.path]
    else:
        # folder(s)
        file_list = []
        if args.recurse:
            for root, sub_folders, files in os.walk(args.path):
                file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]
        else:
            file_list = [os.path.join(args.path, filename) for filename in sorted(os.listdir(args.path)) if is_interesting(args.path, filename)]

    # start time
    start_time = time.time()

    print('Estimating capture time with sub-second precision')
    sub_second_times = estimate_sub_second_time(file_list, args.interval)
    if not sub_second_times:
        sys.exit(1)

    print('Reading GPX file to get track locations')
    use_localtime = True if args.localtime else False
    gpx = get_lat_lon_time(args.gpx_file, use_localtime)

    print("Starting geotagging of {0} images using {1}.\n".format(len(file_list), args.gpx_file))

    for filepath, filetime in zip(file_list, sub_second_times):
        add_exif_using_timestamp(filepath, filetime, gpx, offset_time=args.time_offset, bearing_offset=args.bearing_offset, verbose=args.verbose)

    print("Done geotagging {0} images in {1:.1f} seconds.".format(len(file_list), time.time()-start_time))
