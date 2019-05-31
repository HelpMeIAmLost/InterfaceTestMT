from pandas import ExcelWriter
from sqlite3 import Error
from struct import *

import sqlite3
import argparse
import os
import pandas as pd
import numpy as np

OFF = 0
ON = 1


def data_type_info(data_type):
    any_value = None
    if data_type == np.uint8:
        any_value = 0x7F
    elif data_type == np.uint16:
        any_value = 0x7FFF
    elif data_type == np.uint32:
        any_value = 0x7FFFFFFF
    elif data_type == np.int8:
        any_value = -64
    elif data_type == np.int16:
        any_value = -16384
    elif data_type == np.int32:
        any_value = -1073741824

    if data_type == np.float32:
        return [
            int(float_to_hex(np.finfo(np.float32).max), 16),
            int(float_to_hex(np.finfo(np.float32).min), 16),
            int(float_to_hex(1.23456789), 16)
                ]
    else:
        return [np.iinfo(data_type).max, np.iinfo(data_type).min, any_value]


def raw_to_physical(raw_value, lsb, offset):
    return (raw_value * lsb) + offset


def physical_to_raw(physical_value, lsb, offset):
    return int(((physical_value / lsb) - offset) + 0.5) \
        if physical_value >= 0 else int(((physical_value / lsb) - offset) - 0.5)


def uint8_info(limit):
    if limit == 'min':
        return np.iinfo(np.uint8).min
    elif limit == 'max':
        return np.iinfo(np.uint8).max
    elif limit == 'any':
        return 0x7F
    else:
        return 0


def float32_info(limit):
    if limit == 'min':
        return float_to_hex(np.finfo(np.float32).min)
    elif limit == 'max':
        return float_to_hex(np.finfo(np.float32).max)
    elif limit == 'any':
        return float_to_hex(1.23456789)
    else:
        return 0


def float_to_hex(f):
    return hex(unpack('<I', pack('<f', f))[0])


def hex_to_float(h):
    h = h.lstrip('0x')
    return unpack('!f', bytes.fromhex(h))[0]


def create_connection(db_file):
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return:
        Connection object or None
    """
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

    return None


def execute_sql(conn, sql_statement, values=None, select=False, count=False, just_one=False):
    """ create a table from the create_table_sql statement
    :param conn: SQLite database connection object
    :param sql_statement: SQL statement
    :param values: values to INSERT/UPDATE, in case SQL statement is INSERT/UPDATE request
    :param select: SQL statement is a SELECT statement
    :param count: True if the row count of the SELECT statement will be returned, default is False
    :param just_one: True if the SELECT statement returns only 1 row, default is False
    :return: fetchall() rows for SELECT, 0 for success, -1 for locked database, -2 for something else
    """
    try:
        c = conn.cursor()
        if values is None:
            c.execute(sql_statement)
            if select:
                if count:
                    row_count = 0
                    rows = c.fetchall()
                    for row in rows:
                        row_count += 1
                    return rows, row_count
                else:
                    if just_one:
                        return c.fetchone()
                    else:
                        return c.fetchall()
        else:
            if np.nan in values or '-' in values or '―' in values or 'ー' in values:
                pass
            else:
                c.execute(sql_statement, values)
                if select:
                    if count:
                        row_count = 0
                        rows = c.fetchall()
                        for row in rows:
                            row_count += 1
                        return rows, row_count
                    else:
                        if just_one:
                            return c.fetchone()
                        else:
                            return c.fetchall()
        return 0
    except Error as e:
        if e.__str__().find('UNIQUE constraint failed:') != -1:
            return -2
        elif e.__str__() == 'database is locked':
            return -1
        else:
            print(e, values if values is not None else None)


def commit_disconnect_database(conn):
    """ Commit the changes done to the SQLite database, then close the connection
    :param conn: SQLite database connection object
    :return: None
    """
    conn.commit()
    conn.close()


def write_to_excel(df, filename, sheet_name):
    writer = ExcelWriter(filename)
    df.to_excel(writer, sheet_name, index=False)
    writer.save()
    writer.close()


def read_excel_file(filename, input_data):
    df = pd.read_excel(filename,
                       sheet_name=input_data[0],
                       usecols=input_data[1],
                       skiprows=input_data[2])
    return df


def parse_arguments_for_input_file():
    # Accepting input
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', dest='input_file', help='Variant: -i [filename]')
    args = parser.parse_args()

    if args.input_file:
        return args.input_file
    else:
        return 0


def get_current_directory(filename):
    base_path = os.path.dirname(os.path.realpath(__file__))
    current_file = os.path.join(base_path, filename)
    
    print(current_file)


def reg_replace(data_frame, from_column, regex, str_replace):
    return data_frame[from_column].astype(str).replace(regex, str_replace, regex=True)


def drop(data_frame, from_column, str_drop):
    return data_frame.drop(data_frame[(data_frame[from_column] == str_drop)].index)


def replace(data_frame, from_column, str_before, str_replace):
    return data_frame[from_column].replace(str_before, str_replace)


def insert_lines_of_code(section, filename, data_frame, string, skip_count, spaces):
    """ inserts declarations global variables to the stubs

    :param section: code section to update, declarations or functions
    :param filename: filename of the stub
    :param data_frame: filtered data frame for the current module
    :param string: a line in the stub that indicates the declarations section of the file
    :param skip_count: number of lines to skip from the section header's identifying string
    :param spaces: spacer for the line of code
    :return: return True if updating the file is a success, otherwise, return False
    """
    line_number = find_section_header(filename, string, skip_count)

    if line_number > 0:
        conn = create_connection('interface.db')
        module_name = filename[filename.find('\\')+1:filename.find('.')]
        line_number = line_number + skip_count
        os.rename(filename, '{}.tmp'.format(filename))
        current_line = 1
        rte_api_list = []
        rte_api_list_found = False
        with open('{}.tmp'.format(filename), 'r') as fi:
            with open(filename, 'w') as fo:
                for line in fi:
                    # Check for function call timing
                    if line.find('FUNC(void, {}_CODE) Run_{}'.format(module_name, module_name)) != -1:
                        if str(module_name).find('ms') != -1:
                            cycle_ms = module_name[module_name.find('_')+1:module_name.find('ms')]
                        else:
                            cycle_ms = line[line.find('Run_{}_'.format(module_name))+len(
                                'Run_{}_'.format(module_name)):line.find('ms')]
                        execute_sql(conn,
                                    '''UPDATE internal_signals SET cycle_ms = ? WHERE module = ?''',
                                    (cycle_ms, module_name)
                                    )
                        commit_disconnect_database(conn)
                    # Create a list of RTE APIs
                    if section == 'functions':
                        if line == ' * Input Interfaces:\n':
                            rte_api_list_found = True
                        if rte_api_list_found and line.find(' *   Std_ReturnType ') != -1:
                            rte_api_list.append(line.split()[2].split('(')[0])
                        if line.find('<< Start of documentation area >>') != -1:
                            rte_api_list_found = False

                    fo.write(line)
                    current_line += 1

                    if current_line == (line_number if module_name != 'ACC_Main' and module_name != 'ACC_50ms'
                                        else (line_number - 3)) and section == 'functions':
                        data = data_frame.tolist()
                        temp_declaration_found = False
                        for row in data:
                            # Insert declarations of temporary variables first
                            if str(row).find('Rte_Write_PP_') == -1 and \
                                    str(row).find('Rte_Read_RP_') == -1 and \
                                    str(row).find(' = ') == -1:
                                if row == 'sint16 t_TargetInfo_VRefDist;':
                                    fo.write('{}// {}\n'.format(spaces, row))
                                else:
                                    fo.write('{}{}\n'.format(spaces, row))
                                temp_declaration_found = True
                        if temp_declaration_found:
                            fo.write('\n')

                    if current_line == line_number:
                        data = data_frame.tolist()
                        for row in data:
                            if section == 'declarations':
                                if row == 'float32 FC_Common_EPB_OperationStats;' or \
                                        row == 'float32 PreCAN_EPB_OperationStats;' or \
                                        row == 'float32 Input_SAS_f_SASStopLearn;':
                                    fo.write('{}// {}\n'.format(spaces, row))
                                else:
                                    fo.write('{}{}\n'.format(spaces, row))
                            else:
                                rte_api_found = False
                                if str(row).find('Rte_Write_PP_') != -1 or str(row).find('Rte_Read_RP_') != -1:
                                    function_name = str(row).split('(')[0]
                                    # Check if the function call to be inserted is in the list of RTE APIs
                                    for rte_api_function in rte_api_list:
                                        if rte_api_function == function_name:
                                            rte_api_found = True
                                            break
                                elif str(row).find(' = ') != -1:
                                    rte_api_found = True
                                else:
                                    continue

                                if rte_api_found:
                                    fo.write('{}{}\n'.format(spaces, row))
                                else:
                                    fo.write('{}// {}\n'.format(spaces, row))
            fo.close()
        fi.close()
        os.remove('{}.tmp'.format(filename))
        return True
    elif line_number == -1:
        print('{}{} section of {} is not empty'.format(str(section[:1]).upper(), section[1:], filename))
        return False
    else:
        print('Section header in {} not found'.format(filename))
        return False


def find_section_header(filename, string, skip_count):
    line_number = 1
    insertion_point = skip_count + 1
    insertion_point_start = False
    with open(filename, 'r') as f:
        for line in f:
            if line.find(string) != -1 and not insertion_point_start:
                insertion_point_start = True

            if not insertion_point_start:
                line_number = line_number + 1
            else:
                insertion_point -= 1
                if insertion_point == 0:
                    if line.strip() != '':
                        line_number = -1
                        break
                    else:
                        break
                # nLine = line.strip()
                # if bool(re.match(string, nLine)):
                #     break
                # else:
                #     line_number = line_number + 1
    f.close()
    return line_number
