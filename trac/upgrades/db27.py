from trac.db import Table, Column, Index, DatabaseManager

def do_upgrade(env, ver, cursor):
    """Add new table for links and add two columns to attachment table
    """
    table = Table('ticket_links', key=('source', 'destination', 'type'))[
        Column('source', type='int'),
        Column('destination', type='int'),
        Column('type')]
    db_connector, _ = DatabaseManager(env)._get_connector()
    for stmt in db_connector.to_sql(table):
        cursor.execute(stmt)

    table = Table('attachment', key=('type', 'id', 'filename', 'version'))[
        Column('type'),
        Column('id'),
        Column('filename'), # New
        Column('version', type='int'),
        Column('size', type='int'),
        Column('time', type='int64'),
        Column('description'),
        Column('author'),
        Column('ipnr'),
        Column('status'), # New
        Index(['status'])]
    
    cursor.execute("""CREATE TEMPORARY TABLE at_old AS 
                   SELECT * FROM attachment""")
    cursor.execute("""DROP TABLE attachment""")
    
    for stmt in db_connector.to_sql(table):
        cursor.execute(stmt)
    
    cursor.execute("""INSERT INTO attachment (type, id, filename, version, 
                   size, time, description, author, ipnr, status)
                   SELECT type, id, filename, 1, 
                   size, time, description, author, ipnr, NULL
                   FROM at_old""")
    cursor.execute("""DROP TABLE at_old""")
