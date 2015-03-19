#!/usr/bin/env python
# encoding: utf-8
# Copyright (C) 2015 Space Science and Engineering Center (SSEC),
# University of Wisconsin-Madison.
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# This file is part of the polar2grid software package. Polar2grid takes
# satellite observation data, remaps it, and writes it to a file format for
# input into another program.
# Documentation: http://www.ssec.wisc.edu/software/polar2grid/
#
#     Written by David Hoese    March 2015
#     University of Wisconsin-Madison
#     Space Science and Engineering Center
#     1225 West Dayton Street
#     Madison, WI  53706
#     david.hoese@ssec.wisc.edu
"""Test ll2cr and the extension modules.

:author:       David Hoese (davidh)
:contact:      david.hoese@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2015 University of Wisconsin SSEC. All rights reserved.
:date:         Mar 2015
:license:      GNU GPLv3

"""
__docformat__ = "restructuredtext en"

import os
import sys
import logging
import unittest
import numpy

from polar2grid.remap import ll2cr
from polar2grid.tests.test_remap import create_test_longitude, create_test_latitude

LOG = logging.getLogger(__name__)


dynamic_wgs84 = {
    "grid_name": "test_wgs84_fit",
    "origin_x": None,
    "origin_y": None,
    "width": None,
    "height": None,
    "cell_width": 0.0057,
    "cell_height": -0.0057,
    "proj4_definition": "+proj=latlong +datum=WGS84 +ellps=WGS84 +no_defs",
}


class LL2CRStaticTestCase(unittest.TestCase):
    def test_latlong_basic1(self):
        pass


class LL2CRDynamicTestCase(unittest.TestCase):
    def test_latlong_basic1(self):
        lon_arr = create_test_longitude(-95.0, -75.0, (50, 100))
        lat_arr = create_test_latitude(15.0, 30.0, (50, 100))
        grid_info = dynamic_wgs84.copy()
        ll2cr.ll2cr(lon_arr, lat_arr, grid_info)
        self.assertEqual(lon_arr[0, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid")
        self.assertEqual(lat_arr[-1, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid")

    def test_latlong_basic2(self):
        lon_arr = create_test_longitude(-95.0, -75.0, (50, 100), twist_factor=0.6)
        lat_arr = create_test_latitude(15.0, 30.0, (50, 100), twist_factor=-0.1)
        grid_info = dynamic_wgs84.copy()
        ll2cr.ll2cr(lon_arr, lat_arr, grid_info)
        self.assertEqual(lon_arr[0, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid")
        self.assertEqual(lat_arr[-1, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid")

    def test_latlong_dateline1(self):
        lon_arr = create_test_longitude(165.0, -165.0, (50, 100), twist_factor=0.6)
        lat_arr = create_test_latitude(15.0, 30.0, (50, 100), twist_factor=-0.1)
        grid_info = dynamic_wgs84.copy()
        ll2cr.ll2cr(lon_arr, lat_arr, grid_info)
        self.assertEqual(lon_arr[0, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid over the dateline")
        self.assertEqual(lat_arr[-1, 0], 0, "ll2cr returned the wrong result for a dynamic latlong grid over the dateline")
        self.assertTrue(numpy.all(numpy.diff(lon_arr[0]) >= 0), "ll2cr didn't return monotonic columns over the dateline")


def main():
    return unittest.main()


if __name__ == "__main__":
    sys.exit(main())