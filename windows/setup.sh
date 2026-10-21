#!/bin/bash

set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd ${SCRIPT_DIR}

################################################################################
##    Config
################################################################################

WINE="wine"
# disable mono and gecko popups
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
export WINEPREFIX="${SCRIPT_DIR}/WineRoot"

################################################################################
##    Setting up wine prefix
################################################################################

echo "Setting up a fresh prefix..."
${WINE} wineboot

# Remove auto-created pointless drives that expose the system
rm -f "${WINEPREFIX}/dosdevices/z:"
rm -f "${WINEPREFIX}/dosdevices/"*::

mkdir Data

# Add drives for tools and source/build artifacts
ln -s ../../Tools "${WINEPREFIX}/dosdevices/t:"
ln -s ../../Data "${WINEPREFIX}/dosdevices/d:"
