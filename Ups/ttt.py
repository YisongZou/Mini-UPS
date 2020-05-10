import threading
import socket
from queue import Queue
import world_ups_pb2
import IG1_pb2
from google.protobuf.internal.decoder import _DecodeVarint32
from google.protobuf.internal.encoder import _EncodeVarint
import psycopg2

# execute all commands in cmds on database
def execute_cmds(connection, cmds):
    cursor = connection.cursor()
    for cmd in cmds:
        cursor.execute(cmd)
    connection.commit()

# return truckid of first idle truck
def find_idle_truck(connection):
    cursor = connection.cursor()
    cursor.execute("SELECT \"truckId\" FROM ups_truck WHERE \"truckStatus\" = 'idle';")
    res = cursor.fetchall()
    if len(res) > 0:
        return res[0][0]
    return -1

con = None
try:
    con = psycopg2.connect(user='mqlyyayc', password='qSxcvkfQHBr9DfvQ-CpG-VtExKZK2v0f',
                           host='drona.db.elephantsql.com', port='5432', database='mqlyyayc')
    cursor = con.cursor()
    cursor.execute('SELECT * from ups_package;')
    con.commit()
    res = cursor.fetchall()
    for row in res:
        print(row)

    msg = IG1_pb2.ASendTruck()
    msg.whinfo.whid = 99
    msg.whinfo.x = 5
    msg.whinfo.y = 5
    msg.x = 6
    msg.y = 6
    msg.pkgid = 7
    product1 = msg.products.add()
    product1.id = 9
    product1.description = 'IPhone'
    product1.count = 56
    msg.seq = 77

    upsid = "' ',"
    if msg.HasField('upsid'):
        upsid = "'" + msg.upsid + "'" + ','
    idle_truck_id = find_idle_truck(con)
    print(idle_truck_id)

    cmd_insert_pkg = "INSERT INTO ups_package (\"pkgId\",\"whId\",\"whX\",\"whY\",\"buyerX\",\"buyerY\",\"upsId\"," \
                     "\"truckId\",\"productStatus\") VALUES (" + str(msg.pkgid) + ',' + str(msg.whinfo.whid) + ',' \
                     + str(msg.whinfo.x) + ',' + str(msg.whinfo.y) + ',' + str(msg.x) + ',' + str(msg.y) + ',' \
                     + upsid + str(idle_truck_id) + ',' + "'waiting for pickup');"
    print(cmd_insert_pkg)
    execute_cmds(con, [cmd_insert_pkg])


    cursor.execute(cmd_insert_pkg)
    print(cmd_insert_pkg)

except (Exception, psycopg2.Error) as error:
    print("Error while connecting to PostgreSQL", error)
finally:
    if con:
        con.close()








"""
ucmd = world_ups_pb2.UCommands()
ucmd.simspeed = 90
ucmd.disconnect = False
aa = ucmd.pickups.add()
aa.truckid = 7
aa.whid = 4
aa.seqnum = 2
bb = ucmd.pickups.add()
bb.truckid = 8
bb.whid = 5
bb.seqnum = 3

for pkup in ucmd.pickups:
    print(pkup.truckid)
# print("ucmd.HasField: " + str(ucmd.HasField('deliveries')))

truck_arrive = IG1_pb2.UTruckArrived()
truck_arrive.truckid = 7
truck_arrive.seq = 9

truck_arr = IG1_pb2.UTruckArrived()
truck_arr.CopyFrom(truck_arrive)

umsg = IG1_pb2.UMsg()
a1 = umsg.utruckarrived.add()
a1.CopyFrom(truck_arrive)
a2 = umsg.utruckarrived.add()
a2.CopyFrom(truck_arr)

# print(type(truck_arr) == type(IG1_pb2.UTruckArrived()))
print(isinstance(truck_arr, IG1_pb2.UTruckArrived))
"""



