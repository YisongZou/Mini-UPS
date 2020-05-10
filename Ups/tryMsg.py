import world_ups_pb2
import IG1_pb2
import psycopg2

TRUCK_NUM = 3


def execute_cmds(connection, cmds):
    cursor = connection.cursor()
    for cmd in cmds:
        cursor.execute(cmd)
    connection.commit()


def init_truck_db(connection):
    cmds = []
    for i in range(1, 1 + TRUCK_NUM):
        cmd = "insert into ups_truck (\"truckId\",\"truckX\",\"truckY\",\"truckStatus\",\"pkgId\") values(" \
              + str(i) + "," + str(i) + "," + str(i) + "," + "'idle'" + ",-1);"
        print("cmd: " + cmd)
        cmds.append(cmd)
    execute_cmds(connection, cmds)


connection = None
try:
    connection = psycopg2.connect(user='mqlyyayc', password='qSxcvkfQHBr9DfvQ-CpG-VtExKZK2v0f',
                                       host='drona.db.elephantsql.com', port='5432', database='mqlyyayc')
    init_truck_db(connection)

except (Exception, psycopg2.Error) as error:
    print("Error while connecting to PostgreSQL", error)
finally:
    if connection:
        connection.close()
