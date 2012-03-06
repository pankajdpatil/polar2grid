#!/usr/bin/env python
# encoding: utf-8
"""
viirs_imager_to_swath.py
$Id$

Purpose:
Read one or more contiguous in-order HDF5 VIIRS imager granules in any aggregation
Write out Swath binary files used by ms2gt tools.

Created by rayg@ssec.wisc.edu, Dec 2011.
Copyright (c) 2011 University of Wisconsin SSEC. All rights reserved.
"""

import logging
import sys, os, re, glob
import ctypes as c
import h5py as h5
import numpy as np

from adl_guidebook import MISSING_GUIDE, RE_NPP, FMT_NPP, K_LATITUDE, K_LONGITUDE, K_ALTITUDE, K_RADIANCE, K_REFLECTANCE, K_NAVIGATION, info as _guide_info

LOG = logging.getLogger(__name__)

def _geo_bind(paths):
    "using guidebook, generate geo,img pairs given a sequence of image file paths"
    for pn in paths:
        dn,fn = os.path.split(pn)
        g = _guide_info(fn)
        LOG.debug(repr(g))
        (geo,) = glob.glob(os.path.join(dn,g[K_NAVIGATION]))
        g["geo_path"] = geo
        g["img_path"] = pn
        LOG.debug('file %s uses %s' % (pn, geo))
        yield g

def h5path(hp, path):
    "traverse an hdf5 path to return a nested data object"
    return reduce(lambda x,a: x[a] if a else x, path.split('/'), hp)

def scaling_filter(hp, path):
    "add Filters to the end of a variable, fetch mx+b scaling factors, and return a lambda function to apply them"
    factvar = h5path(hp, path+'Factors')   # FUTURE: make this more elegant please
    (m,b) = factvar[:]
    LOG.debug('scaling factors for %s are (%f,%f)' % (path, m,b))
    return lambda x: x*m + b

def narrate(h5_path_pair_seq, kind = K_RADIANCE):
    """append swath from a sequence of (geo, image) filename pairs to output objects
    """
    for geo_path, image_path in h5_path_pair_seq:
        LOG.debug('geo %s image %s' % (geo_path, image_path))
        idn,ifn = os.path.split(image_path)
        info = _guide_info(ifn)
        ihp = h5.File(image_path, 'r')
        var_path = info[kind]
        LOG.debug('fetching %s from %s' % (var_path, image_path))
        h5v = h5path(ihp, var_path)
        scaler = scaling_filter(ihp, var_path)
        image_data = scaler(h5v[:,:])
        del h5v
        ihp.close()
        del ihp

        gdn,gfn = os.path.split(geo_path)
        gnfo = _guide_info(gfn)
        ghp = h5.File(geo_path, 'r')

        var_path = gnfo[K_LATITUDE]
        LOG.debug('fetching %s from %s' % (var_path, geo_path))
        h5v = h5path(ghp, var_path)
        lat_data = h5v[:,:]
        del h5v

        var_path = gnfo[K_LONGITUDE]
        LOG.debug('fetching %s from %s' % (var_path, geo_path))
        h5v = h5path(ghp, var_path)
        lon_data = h5v[:,:]
        del h5v
        ghp.close()

        mask = MISSING_GUIDE[kind](image_data) if kind in MISSING_GUIDE else None
        yield lon_data, lat_data, image_data, mask



def catenate(image, lat, lon, h5_path_pair_seq, kind = K_RADIANCE):
    """append swath from a sequence of (geo, image) filename pairs to output objects, replacing missing data with -999
    """
    for dlon, dlat, dimg, missing in narrate( h5_path_pair_seq, kind ):
        dimg[missing] = -999
        image.append(dimg)
        lon.append(dlon)
        lat.append(dlat)



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
            self.A = np.array(data)
            self.shape = data.shape
        else:
            self.A = np.concatenate((self.A, data))
            self.shape = self.A.shape
        LOG.debug('array shape is now %s' % repr(self.A.shape))


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
        inform = data.astype(self.dtype) if self.dtype != data.dtype else data
        inform.tofile(self.F)
        self.shape = (self.shape[0] + inform.shape[0], ) + data.shape[1:]
        LOG.debug('%d rows in output file' % self.shape[0])


def swath_to_flat_binary(kind = K_RADIANCE, *pathnames):
    spid = '%d' % os.getpid()
    imname = '.image' + spid
    latname = '.lat' + spid
    lonname = '.lon' + spid
    imfo = file(imname, 'wb')
    lafo = file(latname, 'wb')
    lofo = file(lonname, 'wb')
    imfa = file_appender(imfo, dtype=np.float32)
    lafa = file_appender(lafo, dtype=np.float32)
    lofa = file_appender(lofo, dtype=np.float32)
    catenate(imfa, lafa, lofa, pathnames, kind)
    suffix = '.real4.' + '.'.join(str(x) for x in reversed(imfa.shape))
    os.rename(imname, 'image'+suffix)
    os.rename(latname, 'latitude'+suffix)
    os.rename(lonname, 'longitude'+suffix)



def _test_fbf(*image_paths):
    "convert an image and geo to flat binary files"
    inputs = list(_geo_bind(image_paths))
    gp = [ (d["geo_path"],d["img_path"]) for d in inputs ]
    swath_info = inputs[0]
    LOG.debug(gp)

    swath_to_flat_binary(swath_info["data_kind"], *gp)
    return swath_info

def _test_info(filename):
    m = RE_NPP.match(filename)
    print filename
    print FMT_NPP % m.groupdict()
    print m.groupdict()
    assert( filename == FMT_NPP % m.groupdict() )


def _test_resample(swath, lat, lon):
    "test resampling of swath to grid, may include masked pixels in output"
    from pyresample import kd_tree, geometry
    area_def = geometry.AreaDefinition('areaD', 'Europe (3km, HRV, VTC)', 'areaD' ) # FIXME
    swath_def = geometry.SwathDefinition(lons=lon, lats=lat)
    return kd_tree.resample_gauss(swath_def, image, area_def, radius_of_influence=50000, sigmas=25000, nprocs=2)

def _test_area():
    from pyresample import utils
    area_id = 'mygrid'
    area_name = 'My Grid'
    proj_id = 'mygrid'
    proj4_args = '+proj=laea +lat_0=45 +lon_0=-90 +a=6371228.0 +units=m'
    x_size = 1024
    y_size = 1024
    area_extent = (-4000000,-3000000,4000000,3000000)
    area_def = utils.get_area_def(area_id, area_name, proj_id, proj4_args,
                                  x_size, y_size, area_extent)
    return area_def



def _test1(pfx='SVM04'):
    import glob
    # (geo_fn, ) = glob.glob('GITCO*h5')
    seq = sorted(list(glob.glob(pfx+'*h5')))
    for fn in seq:
        _test_info(os.path.split(fn)[-1])
    LOG.info(repr(seq))
    assert(seq)
    im = array_appender()
    seq = [ (None,x) for x in seq ]
    q = catenate( im, None, None, seq, K_REFLECTANCE )
    return im.A

def _test_show(pat):
    from pylab import imshow, show, bone
    A = _test1(pat)
    A = np.ma.masked_array(A, A>=65533) # for int16 reflectances
    print A.dtype
    print A.min(), A.max(), A.mean()
    imshow(A)
    bone()
    show()
    raw_input('hit enter ')


def _test2(pfx='SVM04'):
    import glob
    import pyresample as pr
    import matplotlib.pyplot as plt

    im,lat,lon = array_appender(), array_appender(), array_appender()
    imfiles = sorted(list(glob.glob(pfx+'*h5')))
    inputs = list(_geo_bind(imfiles))
    geoimg = [ (d["geo_path"],d["img_path"]) for d in inputs ]
    print repr(geoimg)
    q = catenate(im,lat,lon, geoimg, K_REFLECTANCE)
    mask = MISSING_GUIDE[K_REFLECTANCE](im.A)
    data = np.ma.masked_array(im.A, mask)

    area_def = _test_area()
    swath_def = pr.geometry.SwathDefinition(lons=lon.A, lats=lat.A)
    #gridded = pr.kd_tree.resample_gauss(swath_def, data, area_def, radius_of_influence=50000, sigmas=25000, nprocs=2, fill_value=None)
    gridded = pr.kd_tree.resample_nearest(swath_def, data, area_def, radius_of_influence=50000, nprocs=1, fill_value=None)
    pr.plot.save_quicklook('quick.png', area_def, gridded, label='test gridding', backend='Agg')

    #from pylab import imshow, show, bone
    #imshow(gridded)
    #bone()
    #show()

    #bmap = pr.plot.area_def2basemap(area_def)
    #bmng = bmap.bluemarble()
    #col = bmap.imshow(gridded, origin='upper')
    #plt.savefig('bluemarble.png', bbox_inches='tight')
    #raw_input('hit enter ')


def _test3(pfx='SVM04'):
    import glob
    import pyresample as pr
    import matplotlib.pyplot as plt

    im,lat,lon = array_appender(), array_appender(), array_appender()
    imfiles = sorted(list(glob.glob(pfx+'*h5')))
    inputs = list(_geo_bind(imfiles))
    geoimg = [ (d["geo_path"],d["img_path"]) for d in inputs ]
    print repr(geoimg)
    q = catenate(im,lat,lon, geoimg, K_REFLECTANCE)
    mask = MISSING_GUIDE[K_REFLECTANCE](im.A)
    data = np.ma.masked_array(im.A, mask)

    area_def = _test_area()
    swath_def = pr.geometry.SwathDefinition(lons=lon.A, lats=lat.A)
    gridded = pr.kd_tree.resample_gauss(swath_def, data, area_def, radius_of_influence=50000, sigmas=25000, nprocs=1, fill_value=None)
    bmap = pr.plot.area_def2basemap(area_def)

    #gridded = pr.kd_tree.resample_nearest(swath_def, data, area_def, radius_of_influence=50000, nprocs=1, fill_value=None)
    pr.plot.save_quicklook('quick3.png', area_def, gridded, label='test gridding', backend='Agg', dpi=200)





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

    func = args[0]
    args = args[1:]
    globals()[func](*args)
    # FIXME - main() logic code here

    return 0


if __name__=='__main__':
    sys.exit(main())