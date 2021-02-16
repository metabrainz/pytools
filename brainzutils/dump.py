import os
import errno
import logging
import shutil
import subprocess
import tarfile
import tempfile

from flask import current_app


def _create_path(path):
    """Creates a directory structure if it doesn't exist yet."""
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise Exception("Failed to create directory structure %s. Error: %s" % (path, exception))


def _copy_table(cursor, location, table_name, query):
    """Copies data from a table into a file within a specified location.
    Args:
        cursor: a psycopg2 cursor
        location: the directory where the table should be copied.
        table_name: the name of the table to be copied.
        query: the select query for getting data from the table.
    """
    with open(os.path.join(location, table_name), "w") as f:
        logging.info(" - Copying table {table_name}...".format(table_name=table_name))
        copy_query = 'COPY ({query}) TO STDOUT'.format(query=query)
        cursor.copy_expert(copy_query, f)


def _add_file_to_tar_and_delete(location, archive_name, dump_name, tar, filename):
    """Add a file in `location` to an open TarFile at location `archive_name` and then
    delete the file from disk."""
    tar.add(os.path.join(location, filename), arcname=os.path.join(archive_name, dump_name, filename))
    os.remove(os.path.join(location, filename))


def _copy_tables(cursor, location, tables, tar, archive_name, dump_name):
    """ Copy datasets tables into separate files within a specified location (directory).
    """
    for table in tables:
        _copy_table(cursor, location, table, "SELECT %s FROM %s" % (", ".join(tables[table]), table))
        _add_file_to_tar_and_delete(location, archive_name, tar, table, dump_name)


def _dump_tables(cursor, archive_path, dump_name, tables, threads, dump_time, schema_version, license_file):
    """Copies the metadata and the tables to the archive.

    Args:
        archive_path (str): Complete path of the archive that will be created.
        tables (dict): dictionary of tables to dump with table name as key and tuple of columns as value
        threads (int): Maximal number of threads to run during compression.
        dump_time (datetime): Current time.
    """
    archive_name = os.path.basename(archive_path).split('.')[0]
    with open(archive_path, "w") as archive:

        pxz_command = ["pxz", "--compress"]
        if threads is not None:
            pxz_command.append("-T %s" % threads)
        pxz = subprocess.Popen(pxz_command, stdin=subprocess.PIPE, stdout=archive)

        # Creating the archive
        with tarfile.open(fileobj=pxz.stdin, mode="w|") as tar:
            # TODO: Get rid of temporary directories and write directly to tar file if that's possible
            temp_dir = tempfile.mkdtemp()

            try:
                # Adding metadata
                schema_seq_path = os.path.join(temp_dir, "SCHEMA_SEQUENCE")
                with open(schema_seq_path, "w") as f:
                    f.write(str(schema_version))
                tar.add(schema_seq_path, arcname=os.path.join(archive_name, "SCHEMA_SEQUENCE"))

                timestamp_path = os.path.join(temp_dir, "TIMESTAMP")
                with open(timestamp_path, "w") as f:
                    f.write(dump_time.isoformat(" "))
                tar.add(timestamp_path, arcname=os.path.join(archive_name, "TIMESTAMP"))

                tar.add(license_file, arcname=os.path.join(archive_name, "COPYING"))
            except Exception as e:
                current_app.logger.error('Exception while adding dump metadata: %s', str(e), exc_info=True)
                raise

            archive_tables_dir = os.path.join(temp_dir, dump_name, dump_name)  # TODO
            _create_path(archive_tables_dir)
            _copy_tables(cursor, archive_tables_dir, tables, tar, archive_name, dump_name)

            shutil.rmtree(temp_dir)

        pxz.stdin.close()
        pxz.wait()

class Dump:

    def __init__(self):
        pass