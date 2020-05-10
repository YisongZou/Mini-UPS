from socket import *
import world_ups_pb2
import sys

BUF_SIZE = 10000


def create_socket_world(ip, port):
    skt = socket(socket.AF_INET, socket.SOCK_STREAM)
    skt.connect(ip, port)
    print("successfully connected to world")
    return skt


def init_truck():
    trucks = {}
    for i in range(10):
        truck = world_ups_pb2.UInitTruck()
        truck.x = i + 1
        truck.y = i + 1
        trucks.add(truck)
    return trucks


def connect_to_world():
    connect_msg = world_ups_pb2.UConnect()
    connect_msg.isAmazon = False
    connect_msg.trucks = init_truck()
    return connect_msg


def connect_to_world_serial():
    serialized = connect_to_world().SerializeToString()
    return serialized


def parse_connected_msg(connected_msg_str):
    msg = world_ups_pb2.UConnected()
    msg.ParseFromString(connected_msg_str)
    print("ups received UConnected: " + msg.result)


def main():
    args = sys.argv
    world_ip = args[1]       # first argument is world server ip
    world_port = args[2]     # second argument is world server port
    skt = create_socket_world(world_ip, world_port)
    skt.send(connect_to_world_serial())
    connected_msg_str = skt.recv(BUF_SIZE)
    parse_connected_msg(connected_msg_str)


if __name__ == "__main__":
    main()
