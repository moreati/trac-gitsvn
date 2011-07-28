from trac.db import Table, Column, Index, DatabaseManager

def do_upgrade(env, ver, cursor):
    """Add version and status columns to attachment table
    """
    table = Table('attachment', key=('type', 'id', 'filename', 'version'))[
        Column('type'),
        Column('id'),
        Column('filename'),
        Column('version', type='int'),
        Column('size', type='int'),
        Column('time', type='int64'),
        Column('description'),
        Column('author'),
        Column('ipnr'),
        Column('status'),
        Column('deleted', type='int64'), # New
        Index(['status'])]
    
    cursor.execute("""CREATE TEMPORARY TABLE at_old AS 
                   SELECT * FROM attachment""")
    cursor.execute("""DROP TABLE attachment""")
    db_connector, _ = DatabaseManager(env).get_connector()
    for stmt in db_connector.to_sql(table):
        cursor.execute(stmt)
    
    cursor.execute("""INSERT INTO attachment (type, id, filename, version, 
                   size, time, description, author, ipnr, status, deleted)
                   SELECT type, id, filename, version, 
                   size, time, description, author, ipnr, status, NULL
                   FROM at_old""")
    cursor.execute("""DROP TABLE at_old""")
