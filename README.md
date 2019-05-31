# InterfaceTest
## Description
This script tests the interface signals defined in the interface specification by setting maximum, minimum, or any value for non-boolean data types, and ON or OFF for boolean data types. In this version, the following cases are skipped pending upcoming updates:
*  Input and output signals are in CAN
*  Array, maps and tables
*  Input and output signals unreferenced in the stubs, as they won't be assigned an address during compilation
*  Input and output signals having different data types, a conversion factor is required for each pairing and the current IF specification doesn't provide the complete information

## Requirements
Aside from the libraries listed in the requirements.txt file, I used the following:
*  [Python 3.7](https://www.python.org/downloads/release/python-370/)
*  Vector VN1630A with 4 CAN interface

### What's in `requirements.txt`?
*  python-can 3.0.0
*  cantools 28.12.0
*  pandas 0.23.4
*  numpy 1.15.3

## Usage
### Before anything else..
*  The `Build` folder containing the `application.map` file of the target software
*  DBC files should be in the following folder structure relative to the script folder (DBC file names could be different:
```
   ./DBC
      |- <variant 1>
         |- FILE1_<var 1>.dbc
         |- FILE2_<var 1>.dbc
         |- FILE3_<var 1>.dbc
         |- FILE4_<var 1>.dbc
      |- <variant 2>
         |- FILE1_<var 2>.dbc
         |- FILE2_<var 2>.dbc
         |- FILE3_<var 2>.dbc
         |- FILE4_<var 2>.dbc
      :
      |- <variant n>
         |- FILE1_<var n>.dbc
         |- FILE2_<var n>.dbc
         |- FILE3_<var n>.dbc
         |- FILE4_<var n>.dbc
```
*  DBC files are CAN channel-specific. Thus, the script should be updated with the proper channel-DBC file configuration

### Command line syntax
```
py InterfaceTestMT.py variant [-r <number of retries>] [-a <yes/no>] [-m <map folder path>] [-d <DBC folder path>]
```
Where,
  variant - variant to be tested
Options:
  -r <number of retries> - runs the test on failed results from the initial test for the number of retries defined in this option, default is 0
  -a <yes/no> - setting it to yes updates the information of input and output signals, default is no
  -m <map folder path> - points the script to the location of the map file relative to the script location, default is Build/
  -d <DBC folder path> - points the script to the location of the DBC files (with the folder structure described in the Usage section of this readme), default is DBC/

## What's next?
*  Code optimization
*  Generating a simple report
*  Testing of items containing CAN signals as input or output
*  Testing of items that have different input and output signal data types
