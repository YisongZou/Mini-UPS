import threading
import world_thread
import ups_ama_thread
import socket
import world_ups_pb2
import sys
from google.protobuf.internal.decoder import _DecodeVarint32
from google.protobuf.internal.encoder import _EncodeVarint
from queue import Queue
import psycopg2

q_ama = Queue()   # amazon thread send to world thread
q_world = Queue()   # world thread send to amazon thread
sentinel_ama = object()
sentinel_world = object()


def clear_db():
    try:
        connection = None
        connection = psycopg2.connect(user='mqlyyayc', password='qSxcvkfQHBr9DfvQ-CpG-VtExKZK2v0f',
                                      host='drona.db.elephantsql.com', port='5432', database='mqlyyayc')
        cursor = connection.cursor()
        cursor.execute("delete from ups_package;")
        cursor.execute("delete from ups_product;")
        cursor.execute("delete from ups_truck;")

        connection.commit()

    except (Exception, psycopg2.Error) as error:
        print("Error while connecting to PostgreSQL", error)
    finally:
        if connection:
            connection.close()


def main():
    clear_db()

    args = sys.argv
    world_ip = args[1]
    world_port = args[2]

    world_th = world_thread.WorldThread(0, "World", world_ip, int(world_port), q_ama, q_world)
    world_th.start()

    ama_th = ups_ama_thread.UpsAmazonThread(1, "amazon", q_world, q_ama)
    ama_th.start()

    world_th.join()
    ama_th.join()
    print("Finish executing world thread")


if __name__ == "__main__":
    main()
