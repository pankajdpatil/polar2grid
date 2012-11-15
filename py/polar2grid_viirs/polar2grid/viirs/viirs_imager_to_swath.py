#!/usr/bin/env python
# encoding: utf-8
"""
Read one or more contiguous in-order HDF5 VIIRS imager granules in any aggregation
Write out Swath binary files used by ms2gt tools.

:author:       David Hoese (davidh)
:author:       Ray Garcia (rayg)
:contact:      david.hoese@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2012 University of Wisconsin SSEC. All rights reserved.
:date:         Jan 2012
:license:      GNU GPLv3
:revision:     $Id$
"""
__docformat__ = "restructuredtext en"

from .viirs_guidebook import file_info,geo_info,read_file_info,read_geo_info
from .prescale import run_dnb_scale
from .pseudo import create_fog_band
from polar2grid.core.constants import SAT_NPP,INST_VIIRS,BKIND_DNB,NOT_APPLICABLE
from polar2grid.core import roles
import numpy

import os
import sys
import logging
from glob import glob

log = logging.getLogger(__name__)

FILL_VALUE=-999.0

def _glob_file(pat):
    """Globs for a single file based on the provided pattern.

    :raises ValueError: if more than one file matches pattern
    """
    tmp = glob(pat)
    if len(tmp) != 1:
        log.error("There were no files or more than one fitting the pattern %s" % pat)
        raise ValueError("There were no files or more than one fitting the pattern %s" % pat)
    return tmp[0]

def _band_name(band_info):
    return band_info["kind"] + (band_info["band"] or "")

def get_meta_data(ifilepaths, filter=None):
    """Get all meta data for the provided data files.

    :Parameters:
        ifilepaths : list or iterator
            Filepaths for data files to be analyzed
    :Keywords:
        filter : function pointer
            Function that expects a ``finfo`` object as its only argument
            and returns True if the finfo should be accepted, False if not.
            This can be used to specify what types of bands are desired.

    :returns:
        meta_data : dict
            - bands
                dictionary per band of band info containing the following keys:
                    - kind
                    - band
                    - data_kind
                    - remap_data_as
                    - rows_per_scan
                    - fbf_swath
        image_data : dict
            Dictionary where the key is a band ('01','00',etc.) and the
            value is a list of finfo dictionaries.

    :raises ValueError:
        if there is more than one kind of band in provided filenames. We can
        only operate on files that share navigation data
    :raises ValueError:
        if after attempting to process the provided image
        filenames there was no useful data found.
    """
    ifilepaths = sorted(ifilepaths)

    # Data structures
    meta_data = {
            "bands" : {},
            }
    image_data = {}

    # Get image and geonav file info
    bad_bands = []
    for fn in ifilepaths:
        if not os.path.exists(fn):
            log.error("Data file %s does not exist, will try to continue without it..." % fn)
            continue

        try:
            finfo = file_info(fn)
        except StandardError:
            log.error("There was an error getting information from filename '%s'" % fn, exc_info=1)
            log.error("Continuing without that image file...")
            continue

        if filter and not filter(finfo):
            log.debug("File %s was filtered out" % fn)
            continue

        # Verify some information before adding any jobs
        if finfo["band"] in bad_bands:
            log.info("Couldn't add %s because a previous file of that band was bad" % fn)
            continue

        # Geonav file exists
        geo_glob = finfo["geo_glob"]
        try:
            finfo["geo_path"] = _glob_file(geo_glob)
        except ValueError:
            log.error("Couldn't identify geonav file for %s" % fn)
            log.error("Continuing without that band...")
            bad_bands.append(finfo["band"])
            continue

        # Create any locations that don't exist yet
        if (finfo["kind"],finfo["band"]) not in image_data:
            # Fill in data structure
            image_data[(finfo["kind"],finfo["band"])] = []
            meta_data["bands"][(finfo["kind"], finfo["band"])] = {
                    "kind"          : finfo["kind"],
                    "band"          : finfo["band"],
                    "data_kind"     : finfo["data_kind"],
                    "remap_data_as" : finfo["data_kind"],
                    "rows_per_scan" : finfo["rows_per_scan"],
                    "fbf_swath"     : None
                    }

        # Add it to the proper locations for future use
        image_data[(finfo["kind"], finfo["band"])].append(finfo)

    # SANITY CHECK
    if len(image_data) == 0:
        log.error("There aren't any bands left to work on, quitting...")
        raise ValueError("There aren't any bands left to work on, quitting...")

    # Determine what navigation set we are using
    # VIIRS shares navigation between kinds of bands
    first_kind = meta_data["bands"].keys()[0][0]
    for x in meta_data["bands"].keys():
        if x[0] != first_kind:
            msg = "VIIRS frontend requires all files to share navigation, found %s and %s kinds" % (first_kind, x[0])
            log.error(msg)
            raise ValueError(msg)

    meta_data["sat"] = SAT_NPP
    meta_data["instrument"] = INST_VIIRS
    meta_data["nav_set_uid"] = first_kind
    return meta_data,image_data

def get_geo_meta(gfilepaths):
    """Get all meta data from the geo-navigation files provided.

    :Parameters:
        gfilepaths : list
            Filepaths for geo-navigation files to be processed

    :returns:
        meta_data : dict
            Dictionary of meta data derived from the provided filepaths.
            Contains the following keys:

                - start_time
                - swath_rows
                - swath_cols
                - rows_per_scan
                - fbf_lat
                - fbf_lon
                - fbf_mode

        geo_data : list
            List of ginfo dictionaries that can be used to read the
            associated geonav files.

    :attention:
        Just because a key if put in the meta_data dictionary
        does not necessarily mean that that data will be valid or filled
        in after this function has returned.  It will probably be filled
        in during a later step in the swath extraction process.

    :raises ValueError:
        if there is an error processing one of the geonav files.
    """
    geo_data = []
    meta_data = {
            "start_time"  : None,
            "swath_rows"  : None,
            "swath_cols"  : None,
            "rows_per_scan" : None,
            "fbf_lat"   : None,
            "fbf_lon"   : None,
            "fbf_mode"  : None
            }

    for gname in gfilepaths:
        # Get lat/lon information
        try:
            ginfo = geo_info(gname)
        except StandardError:
            log.error("Error getting info from geonav filename %s" % gname)
            raise

        # Add meta data to the meta_data dictionary
        if meta_data["rows_per_scan"] is None:
            meta_data["rows_per_scan"] = ginfo["rows_per_scan"]

        geo_data.append(ginfo)

    return meta_data,geo_data

def process_geo(meta_data, geo_data, cut_bad=False):
    """Read data from the geonav files and put them all
    into 3 concatenated swath files.  One for latitude data, one for
    longitude data, and one for mode (day/night masks) data.
    Has the option of cutting out bad data scans, see ``cut_bad`` below.

    Will add/fill in the following information into the meta_data dictionary:
        - start_time
            Datetime object of the first middle scan time of the
            first granule
        - fbf_lat
            Filename of the flat binary file with latitude data
        - fbf_lon
            Filename of the flat binary file with longitude data
        - fbf_mode
            Filename of the flat binary file with mode data
        - swath_rows
            Number of rows in the concatenated swath
        - swath_cols
            Number of cols in the concatenated swath
        - swath_scans
            Number of scans in the concatenated swath, which is
            equal to ``swath_rows / rows_per_scan``

    :Parameters:
        meta_data : dict
            The meta data dictionary from `get_meta_data`
        geo_data : list
            The list of ``ginfo`` dictionaries from `get_geo_meta`
    :Keywords:
        cut_bad : bool
            Specify whether or not to remove entire scans of data
            when the scan is found to have bad data.  This is done
            because the ms2gt utilities don't know how to handle
            bad geonav data properly.

    :raises ValueError: if there is an error reading in the data from the file
    """
    # Write lat/lon data to fbf files
    # Create fbf files
    spid = '%d' % os.getpid()
    latname = '.lat' + spid
    lonname = '.lon' + spid
    modename = '.mode' + spid
    lafo = file(latname, 'wb')
    lofo = file(lonname, 'wb')
    modefo = file(modename, 'wb')
    lafa = file_appender(lafo, dtype=numpy.float32)
    lofa = file_appender(lofo, dtype=numpy.float32)
    modefa = file_appender(modefo, dtype=numpy.float32)
    lat_south = 91.0
    lat_north = -91.0
    lon_west = 181.0
    lon_east = -181.0

    for ginfo in geo_data:
        # Read in lat/lon data
        try:
            read_geo_info(ginfo, fill_value=FILL_VALUE)
            # Start datetime used in product backend for NC creation
            if meta_data["start_time"] is None:
                meta_data["start_time"] = ginfo["start_time"]
        except StandardError:
            # Can't continue without lat/lon data
            msg = "Error reading data from %s for bands %r" % (ginfo["geo_path"],meta_data["bands"].keys())
            log.error(msg, exc_info=1)
            raise ValueError(msg)

        # ll2cr/fornav hate entire scans that are bad
        scan_quality = ginfo["scan_quality"]
        if cut_bad and len(scan_quality[0]) != 0:
            ginfo["lat_data"] = numpy.delete(ginfo["lat_data"], scan_quality, axis=0)
            ginfo["lon_data"] = numpy.delete(ginfo["lon_data"], scan_quality, axis=0)
            ginfo["mode_mask"] = numpy.delete(ginfo["mode_mask"], scan_quality, axis=0)

        # Calculate min and max lat/lon values for use in remapping
        lat_south = min(lat_south,ginfo["lat_data"][ginfo["lat_data"] != FILL_VALUE].min())
        lat_north = max(lat_north,ginfo["lat_data"][ginfo["lat_data"] != FILL_VALUE].max())
        lon_west_tmp = min(lon_west,ginfo["lon_data"][ginfo["lon_data"] != FILL_VALUE].min())
        lon_east_tmp = max(lon_east,ginfo["lon_data"][ginfo["lon_data"] != FILL_VALUE].max())
        if lon_west_tmp <= -179.0 and lon_east_tmp >= 179.0:
            # We hit the -180/180 boundary
            lon_west_tmp2 = ginfo["lon_data"][(ginfo["lon_data"] != FILL_VALUE) & (ginfo["lon_data"] >= 0)].min()
            lon_west_tmp = min(lon_west, ginfo["lon_data"][(ginfo["lon_data"] != FILL_VALUE) & (ginfo["lon_data"] >= 0)].min())

            lon_east_tmp2 = ginfo["lon_data"][(ginfo["lon_data"] != FILL_VALUE) & (ginfo["lon_data"] <= 0)].max()
            lon_east_tmp = max(lon_east, ginfo["lon_data"][(ginfo["lon_data"] != FILL_VALUE) & (ginfo["lon_data"] <= 0)].max())

        lon_west = lon_west_tmp
        lon_east = lon_east_tmp

        # Append the data to the swath
        lafa.append(ginfo["lat_data"])
        lofa.append(ginfo["lon_data"])
        modefa.append(ginfo["mode_mask"])
        del ginfo["lat_data"]
        del ginfo["lon_data"]
        del ginfo["lat_mask"]
        del ginfo["lon_mask"]
        del ginfo["mode_mask"]

    lafo.close()
    lofo.close()
    modefo.close()

    # Rename files
    suffix = '.real4.' + '.'.join(str(x) for x in reversed(lafa.shape))
    fbf_lat_var = "latitude_%s" % meta_data["nav_set_uid"]
    fbf_lon_var = "longitude_%s" % meta_data["nav_set_uid"]
    fbf_mode_var = "mode_%s" % meta_data["nav_set_uid"]
    fbf_lat = fbf_lat_var + suffix
    fbf_lon = fbf_lon_var + suffix
    fbf_mode = fbf_mode_var + suffix
    os.rename(latname, fbf_lat)
    os.rename(lonname, fbf_lon)
    os.rename(modename, fbf_mode)

    meta_data["fbf_lat"] = fbf_lat
    meta_data["fbf_lon"] = fbf_lon
    meta_data["fbf_mode"] = fbf_mode
    swath_rows,swath_cols = lafa.shape
    meta_data["swath_rows"] = swath_rows
    meta_data["swath_cols"] = swath_cols
    meta_data["swath_scans"] = swath_rows/meta_data["rows_per_scan"]
    log.debug("Data West Lon: %f, North Lat: %f, East Lon: %f, South Lat: %f" % (lon_west,lat_north,lon_east,lat_south))
    meta_data["lat_south"] = lat_south
    meta_data["lat_north"] = lat_north
    meta_data["lon_west"] = lon_west
    meta_data["lon_east"] = lon_east
    meta_data["lon_fill_value"] = FILL_VALUE
    meta_data["lat_fill_value"] = FILL_VALUE

    return meta_data,geo_data

def create_image_swath(swath_rows, swath_cols, swath_scans, fbf_mode,
        band_meta, geo_data, finfos, cut_bad=False):

    # Create fbf files and appenders
    spid = '%d' % os.getpid()
    band_name = _band_name(band_meta)
    imname = '.image_%s.%s' % (band_name, spid)
    imfo = file(imname, 'wb')
    imfa = file_appender(imfo, dtype=numpy.float32)

    # Get the data
    for finfo,ginfo in zip(finfos,geo_data):
        try:
            # XXX: May need to pass the lat/lon masks
            read_file_info(finfo, fill_value=FILL_VALUE)
        except StandardError:
            log.error("Error reading data from %s" % finfo["img_path"])
            raise

        # Cut out bad data
        if cut_bad and len(ginfo["scan_quality"][0]) != 0:
            log.info("Removing %d bad scans from %s" % (len(ginfo["scan_quality"][0])/finfo["rows_per_scan"], finfo["img_path"]))
            finfo["image_data"] = numpy.delete(finfo["image_data"], ginfo["scan_quality"], axis=0)

        # Append the data to the file
        imfa.append(finfo["image_data"])

        # Remove pointers to data so it gets garbage collected
        del finfo["image_data"]
        del finfo["image_mask"]
        del finfo["scan_quality"]
        del finfo

    suffix = '.real4.' + '.'.join(str(x) for x in reversed(imfa.shape))
    img_base = "image_%s" % band_name
    fbf_img = img_base + suffix
    os.rename(imname, fbf_img)
    band_meta["fbf_img"] = fbf_img
    rows,cols = imfa.shape
    band_meta["swath_rows"] = rows
    band_meta["swath_cols"] = cols
    band_meta["swath_scans"] = swath_scans
    band_meta["fbf_mode"] = fbf_mode
    band_meta["fill_value"] = FILL_VALUE

    if rows != swath_rows or cols != swath_cols:
        log.error("Expected %d rows and %d cols, but band %s had %d rows and %d cols" % (swath_rows, swath_cols, band_name, rows, cols))
        raise ValueError("Expected %d rows and %d cols, but band %s had %d rows and %d cols" % (swath_rows, swath_cols, band_name, rows, cols))

    imfo.close()
    del imfa

def process_image(meta_data, image_data, geo_data, cut_bad=False):
    """Read the image data from hdf files and concatenated them
    into 1 swath file.  Has the option to cut out bad data if
    bad navigation data was found, see ``cut_bad`` below.

    :Parameters:
        meta_data : dict
            The meta data dictionary from `get_meta_data`, that's been updated
            through the entire swath extraction process.
        image_data : dict
            Per band dictionary of ``finfo`` dictionary objects from
            `get_meta_data`.
        geo_data : list
            List of ``ginfo`` dictionaries from `get_geo_meta`.
    :Keywords:
        cut_bad : bool
            Specify whether or not to remove entire scans of data
            when the geonav scan is found to have bad data.  This is done
            because the ms2gt utilities don't know how to handle
            bad geonav data properly.

    Information that is updated in the meta data per band dictionary:
        - fbf_img
            Filename of the flat binary file of image data
        - swath_rows
            Number of rows in the swath
        - swath_cols
            Number of columns in the swath
        - swath_scans
            Number of scans in the swath
        - fbf_mode
            Filename of the flat binary file of mode data from `process_geo`
    """
    # Get image data and save it to an fbf file
    for (band_kind,band_id),finfos in image_data.items():
        try:
            create_image_swath(
                    meta_data["swath_rows"],
                    meta_data["swath_cols"],
                    meta_data["swath_scans"],
                    meta_data["fbf_mode"],
                    meta_data["bands"][(band_kind, band_id)],
                    geo_data, finfos, cut_bad=cut_bad)
        except StandardError:
            log.error("Error creating swath for %s, will continue without it..." % _band_name(meta_data["bands"][(band_kind, band_id)]))
            log.debug("Swath error:", exc_info=1)
            del meta_data["bands"][(band_kind, band_id)]
            del image_data[(band_kind, band_id)]
        del finfos

    if len(image_data) == 0:
        log.error("No more bands to process for navigation set %s provided" % meta_data["nav_set_uid"])
        raise ValueError("No more bands to process for navigation set %s provided" % meta_data["nav_set_uid"])

class array_appender(object):
    """wrapper for a numpy array object which gives it a binary data append usable with "catenate"
    """
    A = None
    shape = (0,0)
    def __init__(self, nparray = None):
        if nparray:
            self.A = nparray
            self.shape = nparray.shape

    def append(self, data):
        # append new rows to the data
        if self.A is None:
            self.A = numpy.array(data)
            self.shape = data.shape
        else:
            self.A = numpy.concatenate((self.A, data))
            self.shape = self.A.shape
        log.debug('array shape is now %s' % repr(self.A.shape))


class file_appender(object):
    """wrapper for a file object which gives it a binary data append usable with "catenate"
    """
    F = None
    shape = (0,0)
    def __init__(self, file_obj, dtype):
        self.F = file_obj
        self.dtype = dtype

    def append(self, data):
        # append new rows to the data
        if data is None:
            return
        inform = data.astype(self.dtype) if self.dtype != data.dtype else data
        inform.tofile(self.F)
        self.shape = (self.shape[0] + inform.shape[0], ) + data.shape[1:]
        log.debug('%d rows in output file' % self.shape[0])

def make_swaths(ifilepaths, filter=None, cut_bad=False):
    """Takes SDR hdf files and creates flat binary files for the information
    required to do further processing.

    :Parameters:
        ifilepaths : list
            List of image data filepaths ('SV*') of one kind of band that are
            to be concatenated into a swath.  For example, all of the data
            files for the I bands that are in the same time window.
    :Keywords:
        filter : function pointer
            Function that expects a file info dictionary as its only parameter
            and returns True if that file should continue to be process or
            False if not.
        cut_bad : bool
            Specify whether or not to delete/cut out entire scans of data
            when navigation data is bad.  This is done because the ms2gt
            utilities used for remapping can't handle incorrect navigation data
    """
    # Get meta information from the image data files
    log.info("Getting data file info...")
    meta_data,image_data = get_meta_data(ifilepaths, filter=filter)

    # Extract gfilepaths from the ifilepath information
    # list comprehension here is the fastest way to flatten a list of lists
    gfilepaths = sorted(set( finfo["geo_path"] for band_data in image_data.values() for finfo in band_data ))

    # SANITY CHECK
    g_len = len(gfilepaths)
    for (band_kind, band_id),finfos in image_data.items():
        f_len = len(finfos)
        if f_len != g_len:
            log.error("Expected same number of image and navigation files for every band, removing band...")
            log.error("Got (num ifiles: %d, num gfiles: %d)" % (f_len,g_len))
            del image_data[(band_kind,band_id)]
            del meta_data["bands"][(band_kind, band_id)]

    if len(image_data) == 0:
        log.error("There aren't any bands left to work on, quitting...")
        raise ValueError("There aren't any bands left to work on, quitting...")

    # Get nav data and put it in fbf files
    log.info("Getting geonav file info...")
    geo_meta,geo_data = get_geo_meta(gfilepaths)
    meta_data.update(geo_meta)

    log.info("Creating binary files for latitude and longitude data")
    process_geo(meta_data, geo_data, cut_bad=cut_bad)

    # Get image data and put it in fbf files
    log.info("Creating binary files for image data and day/night masks")
    process_image(meta_data, image_data, geo_data, cut_bad=cut_bad)

    return meta_data

class Frontend(roles.FrontendRole):
    def __init__(self):
        pass

    def make_swaths(self, *args, **kwargs):
        scale_dnb = kwargs.pop("scale_dnb", False)
        new_dnb = kwargs.pop("new_dnb", False)
        create_fog = kwargs.pop("create_fog", False)

        meta_data = make_swaths(*args, **kwargs)
        bands = meta_data["bands"]

        # These steps used to be part of the glue scripts
        # Due to laziness they are just called as separate functions here
        if create_fog:
            try:
                create_fog_band(bands)
            except StandardError:
                log.error("Fog band creation failed")
                raise

        # These steps used to be part of the glue scripts
        # Due to laziness they are just called as separate functions here
        for (band_kind, band_id),band_job in bands.items():
            if band_kind != BKIND_DNB or not scale_dnb:
                # We don't need to scale non-DNB data
                band_job["fbf_swath"] = band_job["fbf_img"]
                continue

            log.info("Prescaling DNB data...")
            try:
                fbf_swath = run_dnb_scale(
                        band_job["fbf_img"],
                        band_job["fbf_mode"],
                        new_dnb=new_dnb # XXX
                        )
                band_job["fbf_swath"] = fbf_swath
            except StandardError:
                log.error("Unexpected error DNB, removing job...")
                log.debug("DNB scaling error:", exc_info=1)
                del bands[(band_kind, band_id)]

        return meta_data

def main():
    import optparse
    usage = """
%prog [options] filename1.h,filename2.h,filename3.h,... struct1,struct2,struct3,...

"""
    parser = optparse.OptionParser(usage)
    parser.add_option('-t', '--test', dest="self_test",
                    action="store_true", default=False, help="run self-tests")
    parser.add_option('-v', '--verbose', dest='verbosity', action="count", default=0,
                    help='each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG')
    # parser.add_option('-o', '--output', dest='output',
    #                 help='location to store output')
    # parser.add_option('-I', '--include-path', dest="includes",
    #                 action="append", help="include path to append to GCCXML call")
    (options, args) = parser.parse_args()

    # make options a globally accessible structure, e.g. OPTS.
    global OPTS
    OPTS = options

    if options.self_test:
        import doctest
        doctest.testmod()
        sys.exit(0)

    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    logging.basicConfig(level = levels[min(3, options.verbosity)])

    if not args:
        parser.error( 'incorrect arguments, try -h or --help.' )
        return 9

    import json
    meta_data = make_swaths(args[:])
    print json.dumps(meta_data)
    return 0

if __name__=='__main__':
    sys.exit(main())