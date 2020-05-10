import threading
import socket
import world_ups_pb2
import sys
from google.protobuf.internal.decoder import _DecodeVarint32
from google.protobuf.internal.encoder import _EncodeVarint
from queue import Queue
import psycopg2
import time

msg_from_world = Queue()
to_send = Queue()
ack_from_world = set()
mutex = threading.Lock()    # locker for ack_from_world
TRUCK_NUM = 10
SIM_SPEED = 100

def parse_ures_msg(msg_str):
    msg = world_ups_pb2.UResponses()
    msg.ParseFromString(msg_str)
    return msg


def send_msg_str_to_wld(msg_str, wld_skt):
    _EncodeVarint(wld_skt.send, len(msg_str), None)
    wld_skt.send(msg_str)


def parse_ures(msg_str):
    msg = world_ups_pb2.UResponses()
    msg.ParseFromString(msg_str)
    return msg


def parse_uconnected(msg_str):
    msg = world_ups_pb2.UConnected()
    msg.ParseFromString(msg_str)
    return msg


def recv_msg_str_from_wld(wld_skt):
    var_int_buff = []
    while True:
        buf = wld_skt.recv(1)
        var_int_buff += buf
        msg_len, new_pos = _DecodeVarint32(var_int_buff, 0)
        if new_pos != 0:
            break
    whole_message_str = wld_skt.recv(msg_len)
    return whole_message_str


# execute all commands in cmds on database
def execute_cmds(connection, cmds):
    cursor = connection.cursor()
    for cmd in cmds:
        cursor.execute(cmd)
    connection.commit()


def create_socket_world(word_ip, world_port):
    skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    skt.connect((word_ip, world_port))
    print("wld_th successfully connected to world")
    return skt


def uconnect_msg():
    connect_msg = world_ups_pb2.UConnect()
    connect_msg.isAmazon = False
    for i in range(1, 1 + TRUCK_NUM):
        connect_msg.trucks.add(id=i, x=i, y=i)
    return connect_msg


def connect_to_world_serial():
    serialized = uconnect_msg().SerializeToString()
    return serialized


def parse_connected_msg(connected_msg_str):
    msg = world_ups_pb2.UConnected()
    msg.ParseFromString(connected_msg_str)
    print("world_th ups received UConnected: " + msg.result)
    print("world_th ups received worldid: " + str(msg.worldid))
    return msg.worldid


def put_acks_on_tosend(acks):
    msg = world_ups_pb2.UCommands()
    for ack in acks:
        msg.acks.append(ack)
    to_send.put(msg)


class WorldThread(threading.Thread):
    def __init__(self, threadID, name, world_ip, world_port, in_queue, out_queue):
        threading.Thread.__init__(self)
        self.threadID = threadID
        self.name = name
        self.world_ip = world_ip
        self.world_port = world_port
        self.skt = create_socket_world(world_ip, world_port)
        self.in_q = in_queue
        self.out_q = out_queue
        self.th0_quit = False
        self.th1_quit = False
        self.th2_quit = False
        self.connection = None

    def init_truck_db(self):
        cmds = []
        for i in range(1, 1 + TRUCK_NUM):
            cmd = "insert into ups_truck (\"truckId\",\"truckX\",\"truckY\",\"truckStatus\",\"pkgId\") values(" \
                  + str(i) + "," + str(i) + "," + str(i) + "," + "'idle'" + ",-1);"
            cmds.append(cmd)
        execute_cmds(self.connection, cmds)

    # responsible for receiving msg from world, put on ack || msg || out_queue
    def th0(self):
        while not self.th0_quit:
            msg = parse_ures_msg(recv_msg_str_from_wld(self.skt))

            # collect acks
            with mutex:
                for ack in msg.acks:
                    ack_from_world.add(ack)
                    print("world th0 ack received: " + str(ack))

            """
            mutex.acquire()
            for ack in msg.acks:
                ack_from_world.add(ack)
                print("world th0 ack received: " + str(ack))
            mutex.release()
            """

            seq_received = []
            # collect UFinished and UDeliveryMade & put on out_q
            for complete in msg.completions:
                msg_from_world.put(complete)
                self.out_q.put(complete)
                seq_received.append(complete.seqnum)
                print("world th0 complete received: " + str(complete))
            for deli in msg.delivered:
                msg_from_world.put(deli)
                self.out_q.put(deli)
                seq_received.append(deli.seqnum)
                print("world th0 delivered received: " + str(deli))
            for truck_status in msg.truckstatus:
                msg_from_world.put(truck_status)
                self.out_q.put(truck_status)
                seq_received.append(truck_status.seqnum)
                print("world th0 truck status received: " + str(truck_status))
            if msg.HasField('finished'):
                self.out_q.put(msg)
                self.th0_quit = True
                self.th1_quit = True
                self.th2_quit = True
            for err in msg.error:
                print(err)
                self.out_q.put(err)
                seq_received.append(err.seqnum)
            put_acks_on_tosend(seq_received)

    # th1 reads from in_queue, put corresponding msg on to_send
    def th1(self):
        while not self.th1_quit:
            if not self.in_q.empty():
                # msg can be UGoPickup or UGoDeliver, directly put on to_send
                msg = self.in_q.get()
                print("world th1 in_q read: " + str(msg))
                to_send.put(msg)

    # th3 used to send msg, wait 2s, if no ack received, send it again
    def th3(self, msg, seq):
        while True:
            send_msg_str_to_wld(msg.SerializeToString(), self.skt)
            time.sleep(2)
            with mutex:
                if seq in ack_from_world:
                    print("world th3 ack received: " + str(seq))
                    ack_from_world.remove(seq)
                    print("world th3 send successfully: " + str(msg))
                    break

            """
            mutex.acquire()
            if seq in ack_from_world:
                print("world th3 ack received: " + str(seq))
                ack_from_world.remove(seq)
                print("world th3 send successfully: " + str(msg))
                break
            mutex.release()
            """

    # t2 responsible for fetch from to_send, send msg to world
    def th2(self):
        while not self.th2_quit:
            if not to_send.empty():
                msg = to_send.get()
                ucmd_msg = world_ups_pb2.UCommands()
                if isinstance(msg, world_ups_pb2.UCommands):
                    send_msg_str_to_wld(msg.SerializeToString(), self.skt)
                else:
                    seq = msg.seqnum
                    if isinstance(msg, world_ups_pb2.UGoPickup):
                        pkup = ucmd_msg.pickups.add()
                        pkup.CopyFrom(msg)
                        print("world th2 UGoPickup put on to_send: " + str(ucmd_msg))
                    elif isinstance(msg, world_ups_pb2.UGoDeliver):
                        deli = ucmd_msg.deliveries.add()
                        deli.CopyFrom(msg)
                        print("world th2 UGoDeliver put on to_send: " + str(ucmd_msg))
                    th3_new = threading.Thread(target=self.th3, args=(ucmd_msg, seq))
                    th3_new.start()

    def recv_msg_str_from_world(self):
        var_int_buff = []
        while True:
            buf = self.skt.recv(1)
            var_int_buff += buf
            msg_len, new_pos = _DecodeVarint32(var_int_buff, 0)
            if new_pos != 0:
                break
        whole_message_str = self.skt.recv(msg_len)
        return whole_message_str

    def connect_to_world(self):
        send_msg_str_to_wld(uconnect_msg().SerializeToString(), self.skt)
        uconnected_msg = world_ups_pb2.UConnected()
        uconnected_msg.ParseFromString(recv_msg_str_from_wld(self.skt))
        self.out_q.put(uconnected_msg)

    def run(self):
        try:
            self.connection = psycopg2.connect(user='mqlyyayc', password='qSxcvkfQHBr9DfvQ-CpG-VtExKZK2v0f',
                                               host='drona.db.elephantsql.com', port='5432', database='mqlyyayc')
            self.connect_to_world()   # create a world
            self.init_truck_db()    # initialize truck table

            # initialize sim_speed
            msg = world_ups_pb2.UCommands()
            msg.simspeed = SIM_SPEED
            to_send.put(msg)

            recv_thread = threading.Thread(target=self.th0)
            read_in_q_thread = threading.Thread(target=self.th1)
            send_thread = threading.Thread(target=self.th2)

            recv_thread.start()
            read_in_q_thread.start()
            send_thread.start()

            recv_thread.join()
            read_in_q_thread.join()
            send_thread.join()

            """
            send_msg_to_world(connect_to_world_serial(), self.skt)

            connected_msg_str = self.recv_msg_str_from_world()
            # world_id = parse_connected_msg(connected_msg_str)
            # self.out_q.put(world_id)
            msg = world_ups_pb2.UConnected()
            msg.ParseFromString(connected_msg_str)
            print(msg)
            self.out_q.put(msg)
            while True:
                x = 9
            """

        except (Exception, psycopg2.Error) as error:
            print("Error while connecting to PostgreSQL", error)
        finally:
            if self.connection:
                self.connection.close()