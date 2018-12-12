from pandas import ExcelWriter
from sqlite3 import Error
from struct import *

import sqlite3
import argparse
import os
import pandas as pd
import numpy as np


def uint8_info(limit):
    if limit == 'min':
        return np.iinfo(np.uint8).min
    elif limit == 'max':
        return np.iinfo(np.uint8).max
    elif limit == 'any':
        return 0x7F
    else:
        return 0


def float32_info(limit, to_hex=False):
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
        if e.__str__().find('UNIQUE constraint failed:') == -1:
            print(e, values if values is not None else None)
        elif e.__str__() == 'database is locked':
            return -1
        else:
            print(e)
            return -2


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
