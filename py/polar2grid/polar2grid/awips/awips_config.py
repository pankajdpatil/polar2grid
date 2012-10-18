#!/usr/bin/env python
# encoding: utf-8
"""Functions to read configuration files for the viirs2awips.

Instances of default configuration file locations and contents.

Configuration files from which the above are derived
Global objects representing configuration files

:Variables:
    GRIDS : dict
        Mappings to product_id, NC filename format,
        and other meta data needed for NC files
    BANDS : dict
        Mappings to product_id, NC filename format,
        and other meta data needed for NC files
    GRID_TEMPLATES : dict
        Mappings to gpd and NC templates.
    SHAPES : dict 
        Mappings of grid name to lat/lon boundaries and coverage percentage
    PRODUCTS_FILE
        File holding band to grid mappings, including product_id and NC
        filename format
    ANCIL_DIR
        Directory holding gpd and nc templates for AWIPS grids.
    SHAPES_FILE
        File holding grid boundaries for grids specified in the
        grids directory and products.conf file

:author:       David Hoese (davidh)
:contact:      david.hoese@ssec.wisc.edu
:organization: Space Science and Engineering Center (SSEC)
:copyright:    Copyright (c) 2012 University of Wisconsin SSEC. All rights reserved.
:date:         Jan 2012
:license:      GNU GPLv3
:revision:     $Id$
"""
__docformat__ = "restructuredtext en"

from xml.etree import cElementTree
from polar2grid.nc import ncml_tag
from polar2grid.core.constants import NOT_APPLICABLE

import os
import sys
import logging

log = logging.getLogger(__name__)

script_dir = os.path.split(os.path.realpath(__file__))[0]
# Default config file if none is specified
DEFAULT_CONFIG_NAME = "awips_grids.conf"
DEFAULT_CONFIG_FILE = os.path.join(script_dir, DEFAULT_CONFIG_NAME)
# Default search directory for any awips configuration files
DEFAULT_CONFIG_DIR = script_dir
# Default search directory for NCML files
DEFAULT_NCML_DIR = os.path.join(script_dir, "ncml")

# Get configuration file locations
CONFIG_FILE = os.environ.get("AWIPS_CONFIG_FILE", DEFAULT_CONFIG_FILE)
CONFIG_DIR  = os.environ.get("AWIPS_CONFIG_DIR", DEFAULT_CONFIG_DIR)
NCML_DIR    = os.environ.get("AWIPS_NCML_DIR", DEFAULT_NCML_DIR)


PERSISTENT_CONFIGS = {}

def find_grid_templates(ancil_dir):
    grid_templates = {}
    # Get a set of the "grid211" part of every template
    for t in set([x.split(".")[0] for x in os.listdir(ANCIL_DIR) if x.startswith("grid")]):
        nc_temp = t + ".ncml"
        gpd_temp = t + ".gpd"
        nc_path = os.path.join(ANCIL_DIR, nc_temp)
        gpd_path = os.path.join(ANCIL_DIR, gpd_temp)
        grid_number = t[4:]
        if os.path.exists(nc_path) and os.path.exists(gpd_path):
            grid_templates[grid_number] = (gpd_path, nc_path)
    return grid_templates

# This isn't used anymore, but its a handy function to hold on to
# This was replaced by the grids/grids.py API which requires grid size to be
# in the grids.conf file
def get_shape_from_ncml(fn, var_name):
    """Returns (rows,cols) of the variable with name
    `var_name` in the ncml file with filename `fn`.
    """
    xml_parser = cElementTree.parse(fn)
    all_vars = xml_parser.findall(ncml_tag("variable"))
    important_var = [ elem for elem in all_vars if elem.get("name") == var_name]
    if len(important_var) != 1:
        log.error("Couldn't find a variable with name %s in the ncml file %s" % (var_name,fn))
        raise ValueError("Couldn't find a variable with name %s in the ncml file %s" % (var_name,fn))
    important_var = important_var[0]

    # Get the shape out
    shape = important_var.get("shape")
    if shape is None:
        log.error("NCML variable %s does not have the required shape attribute" % (var_name,))
        raise ValueError("NCML variable %s does not have the required shape attribute" % (var_name,))

    # Get dimension names from shape attribute
    shape_dims = shape.split(" ")
    if len(shape_dims) != 2:
        log.error("2 dimensions are required for variable %s" % (var_name,))
        raise ValueError("2 dimensions are required for variable %s" % (var_name,))
    rows_name,cols_name = shape_dims

    # Get the dimensions by their names
    all_dims = xml_parser.findall(ncml_tag("dimension"))
    important_dims = [ elem for elem in all_dims if elem.get("name") == rows_name or elem.get("name") == cols_name ]
    if len(important_dims) != 2:
        log.error("Corrupt NCML file %s, can't find both of %s's dimensions" % (fn, var_name))
        raise ValueError("Corrupt NCML file %s, can't find both of %s's dimensions" % (fn, var_name))

    if important_dims[0].get("name") == rows_name:
        rows = int(important_dims[0].get("length"))
        cols = int(important_dims[1].get("length"))
    else:
        rows = int(important_dims[1].get("length"))
        cols = int(important_dims[0].get("length"))
    return rows,cols

def _create_config_id(sat, instrument, kind, band, data_kind, grid_name=None):
    if grid_name is None:
        # This is used for searching the configs
        return "_".join([sat, instrument, kind, band or "", data_kind])
    else:
        # This is used for adding to the configs
        return "_".join([sat, instrument, kind, band or "", data_kind, grid_name])

def _rel_to_abs(filename, default_base_path):
    """Function that checks if a filename provided is not an absolute
    path.  If it is not, then it checks if the file exists in the current
    working directory.  If it does not exist in the cwd, then the default
    base path is used.  If that file does not exist an exception is raised.
    """
    if not os.path.isabs(filename):
        cwd_filepath = os.path.join(os.path.curdir, filename)
        if os.path.exists(cwd_filepath):
            filename = cwd_filepath
        else:
            filename = os.path.join(default_base_path, filename)
    filename = os.path.realpath(filename)

    if not os.path.exists(filename):
        log.error("File '%s' could not be found" % (filename,))
        raise ValueError("File '%s' could not be found" % (filename,))

    return filename

def load_config_str(name, config_str):
    # Don't load a config twice
    if name in PERSISTENT_CONFIGS:
        return True

    # Get rid of trailing new lines and commas
    config_lines = [ line.strip(",\n") for line in config_str.split("\n") ]
    # Get rid of comment lines and blank lines
    config_lines = [ line for line in config_lines if line and not line.startswith("#") and not line.startswith("\n") ]
    # Check if we have any useful lines
    if not config_lines:
        log.warning("No non-comment lines were found in '%s'" % name)
        return False

    PERSISTENT_CONFIGS[name] = {}

    try:
        # Parse config lines
        for line in config_lines:
            parts = line.split(",")
            if len(parts) != 12:
                log.error("AWIPS config line needs exactly 12 columns '%s' : '%s'" % (name,line))
                raise ValueError("AWIPS config line needs exactly 12 columns '%s' : '%s'" % (name,line))

            # Verify that each identifying portion is valid
            for i in range(6):
                assert parts[i],"Field %d can not be empty" % i
                # polar2grid demands lowercase fields
                parts[i] = parts[i].lower()

            # Convert band if none
            if parts[3] == '' or parts[3] == "none":
                parts[3] = NOT_APPLICABLE

            line_id = _create_config_id(*parts[:6])
            if line_id in PERSISTENT_CONFIGS[name]:
                log.error("AWIPS config has 2 entries for %s" % (line_id,))
                raise ValueError("AWIPS config has 2 entries for %s" % (line_id,))

            # Parse out the awips specific elements
            product_id = parts[6]
            awips2_channel = parts[7]
            awips2_source = parts[8]
            awips2_satellitename = parts[9]
            ncml_template = _rel_to_abs(parts[10], NCML_DIR)
            nc_format = parts[11]
            config_entry = {
                    "grid_name" : parts[5],
                    "product_id" : product_id,
                    "awips2_channel" : awips2_channel,
                    "awips2_source" : awips2_source,
                    "awips2_satellitename" : awips2_satellitename,
                    "ncml_template" : ncml_template,
                    "nc_format" : nc_format
                    }
            PERSISTENT_CONFIGS[name][line_id] = config_entry
    except StandardError:
        # Clear out the bad config
        del PERSISTENT_CONFIGS[name]
        raise

    return True

def load_config(config_filename=None, config_name=None):
    if config_filename is None:
        config_filename = DEFAULT_CONFIG_FILE
        config_name = DEFAULT_CONFIG_NAME
    if config_name is None: config_name = config_filename

    # Load a configuration file, even if it's in the package
    config_filename = _rel_to_abs(config_filename, CONFIG_DIR)

    log.debug("Using AWIPS configuration '%s'" % (config_filename,))

    if config_filename in PERSISTENT_CONFIGS:
        return True

    config_file = open(config_filename, 'r')
    config_str = config_file.read()
    return load_config_str(config_name, config_str)

def can_handle_inputs(sat, instrument, kind, band, data_kind):
    """Search through the configuration files and return all the grids for
    this band and data_kind
    """
    band_id = _create_config_id(sat, instrument, kind, band, data_kind)
    log.debug("Searching AWIPS configs for '%s'" % (band_id,))
    grids = []
    for config_file,config_dict in PERSISTENT_CONFIGS.items():
        for k in config_dict.keys():
            if k.startswith(band_id):
                grids.append(config_dict[k]["grid_name"])
    return grids

def get_awips_info(sat, instrument, kind, band, data_kind, grid_name, config_name):
    if config_name not in PERSISTENT_CONFIGS:
        log.error("Information was asked for about a config file that wasn't loaded: '%s'" % (config_name,))
        raise ValueError("Information was asked for about a config file that wasn't loaded: '%s'" % (config_name,))

    config_id = _create_config_id(sat, instrument, kind, band, data_kind, grid_name)
    if config_id not in PERSISTENT_CONFIGS[config_name]:
        log.error("'%s' could not be found in the loaded configuration '%s', available '%r'" % (config_id,config_name,PERSISTENT_CONFIGS[config_name].keys()))
        raise ValueError("'%s' could not be found in the loaded configuration '%s'" % (config_id,config_name))

    return PERSISTENT_CONFIGS[config_name][config_id]

if __name__ == "__main__":
    sys.exit(0)
