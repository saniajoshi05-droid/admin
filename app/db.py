"""Database helpers for the admin dashboard.

These allow the app to quickly and easily make database queries.

The database credentials are defined in config.py.
"""
import pymysql
from flask import g

import config


def get_connection():
    """Return this request's database connection, opening one if needed."""
    if "db" not in g:
        g.db = pymysql.connect(
            host=config.DB_HOST,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
    return g.db


def close_connection(exception=None):
    """Close this request's connection. Registered as a Flask teardown hook."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=None):
    """Run a SELECT and return every matching row as a list of dicts."""
    with get_connection().cursor() as cursor:
        cursor.execute(sql, args)
        return cursor.fetchall()


def query_one(sql, args=None):
    """Run a SELECT and return the first matching row, or None."""
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql, args=None):
    """Run an INSERT/UPDATE/DELETE. Returns the new row's id for inserts."""
    with get_connection().cursor() as cursor:
        cursor.execute(sql, args)
        return cursor.lastrowid

