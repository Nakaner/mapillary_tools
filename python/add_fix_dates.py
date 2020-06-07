#!/usr/bin/python

import argparse
import sys
import os
import datetime
import pyexiv2
import math
import time
from pyexiv2.utils import make_fraction




def add_exif_using_timestamp(filename, start_time, offset_time, verbose):
    '''
    Find lat, lon and bearing of filename and write to EXIF.
    '''

    metadata = pyexiv2.ImageMetadata(filename)
    metadata.read()
    t = start_time + datetime.timedelta(seconds=int(offset_time))
    if verbose:
        print("setting {0} time to {1} due to offset {2}".format(filename, t, offset_time))
	
    try:
       metadata["Exif.Photo.DateTimeOriginal"] = t;
       metadata["Exif.Photo.SubSecTimeOriginal"] = str(int((offset_time%1) * 1000))
       metadata.write()
    except ValueError as e:
        print("Skipping {0}: {1}".format(filename, e))


def is_interesting(directory, fname):
    p1, p2 = os.path.splitext(fname)
    if p2.lower() == '.jpg' and os.path.isfile(os.path.join(directory, fname)):
        return True
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='''Script for adding dates to jpg files extracted from video with no tags. if you have a directory of files
provide the directory, the datetime for the first file, and an increment in seconds. This means, if the photos are
taken every 2 seconds 
python add_fix_dates.py /home/me/myphotos/ '2014-11-27 13:01:01' 2

Using UTC is recommended.

!!! This version needs testing, please report issues.!!!

Requires pyexiv2, see install instructions at http://tilloy.net/dev/pyexiv2/
''',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-r', '--recurse', action='store_true', help='Work recursive on all subdirectories.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('images_path', type=str, help='Path to the directory where the images are stored, or to a single JPEG file.')
    parser.add_argument('start_time', type=str, help='Date and time in the following format: 2014-11-27 13:01:01')
    parser.add_argument('increment', type=float, help='Increment in seconds.')
    args = parser.parse_args()

    path = args.images_path
    start_time = args.start_time
    time_offset = args.increment
    
    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    elif os.path.isdir(path):
        # folder(s)
        file_list = []
        if args.recurse:
            for root, sub_folders, files in os.walk(path):
                file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]
        else:
            file_list = [os.path.join(path, filename) for filename in sorted(os.listdir(path)) if is_interesting(path, filename)]
    else:
        sys.stderr.write('ERROR: {} is neither a JPEG file nor a directory.\n'.format(path))

    inc = 0
    file_list.sort()
    start_time_dt = datetime.datetime.strptime(start_time,'%Y-%m-%d %H:%M:%S');

    for filepath in file_list:
            add_exif_using_timestamp(filepath, start_time_dt, inc, args.verbose) 
            inc = inc + time_offset    

   
