import sqlite3
import pytest
from app.agent import demo_plan
from shared.store import Store


def test_ambiguous_queries_are_not_silently_reduced():
    schema=[{'name':name,'type':'DOUBLE' if name in {'sales','cost'} else 'VARCHAR'} for name in ['sales','cost','region','month']]
    for query in ['按区域比较销售额和成本','按区域比较销售额，再看按月趋势']:
        with pytest.raises(ValueError):
            demo_plan(query,schema)


def test_connection_closes_and_failed_transaction_rolls_back(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    with store.connect() as connection:
        connection.execute('SELECT 1')
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute('SELECT 1')
    with pytest.raises(RuntimeError):
        with store.connect() as connection:
            connection.execute("INSERT INTO receipts VALUES ('test','{}','receipt')")
            raise RuntimeError('injected failure')
    with store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0
