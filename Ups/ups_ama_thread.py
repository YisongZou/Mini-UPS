import threading
import socket
from queue import Queue
import world_ups_pb2
import IG1_pb2
from google.protobuf.internal.decoder import _DecodeVarint32
from google.protobuf.internal.encoder import _EncodeVarint
import time
import psycopg2


HOST = socket.gethostbyname(socket.gethostname())
PORT = 33333
msg_from_ama = Queue()
to_send = Queue()
ack_from_ama = set()
mutex = threading.Lock()    # locker for ack_from_ama
seq_locker = threading.Lock()    # locker for sequence
order_to_be_placed = Queue()
seq_from_ama = set()   # record all sequence from amazon, if already existed, don't put on msg_from_ama
seq_from_ama_lock = threading.Lock()


def create_socket():
    skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    skt.bind((HOST, PORT))
    skt.listen()
    ipaddr, port = skt.getsockname()
    print("ipaddr: " + ipaddr)
    print("port: " + str(port))
    return skt


def parse_amsg(msg_str):
    msg = IG1_pb2.AMsg()
    msg.ParseFromString(msg_str)
    return msg


def send_msg_str_to_ama(msg_str, ama_skt):
    _EncodeVarint(ama_skt.send, len(msg_str), None)
    ama_skt.send(msg_str)


def recv_msg_str_from_ama(ama_skt):
    var_int_buff = []
    while True:
        buf = ama_skt.recv(1)
        var_int_buff += buf
        msg_len, new_pos = _DecodeVarint32(var_int_buff, 0)
        if new_pos != 0:
            break
    whole_message_str = ama_skt.recv(msg_len)
    return whole_message_str


# execute all commands in cmds on database
def execute_cmds(connection, cmds):
    cursor = connection.cursor()
    for cmd in cmds:
        cursor.execute(cmd)
    connection.commit()

# create umsg with ack, put onto to_send
def put_ack_umsg(ack):
    ack_umsg = IG1_pb2.UMsg()
    ack_umsg.acks.append(ack)
    to_send.put(ack_umsg)


class UpsAmazonThread(threading.Thread):
    def __init__(self, threadID, name, in_queue, out_queue):
        threading.Thread.__init__(self)
        self.listen_port = PORT
        self.server_skt = create_socket()
        self.thread_id = threadID
        self.name = name
        self.in_q = in_queue
        self.out_q = out_queue
        self.quited = False
        self.seq = 1
        self.th0_quit = False
        self.th1_quit = False
        self.th2_quit = False
        self.th3_quit = False
        self.connection = None

    def accept_ama(self):
        print("BEFORE ACCEPT AMAZON")
        return self.server_skt.accept()

    # read current sequence value & increase seq value by 1
    def fetch_seq_and_inc(self):
        seq_locker.acquire()
        cur_seq = self.seq
        self.seq = self.seq + 1
        seq_locker.release()
        return cur_seq

    # th0 responsible for receive msg from amazon
    def th0(self, ama_skt):
        while not self.th0_quit:
            print("ama_th th0 before recving from amazon msg")
            msg = parse_amsg(recv_msg_str_from_ama(ama_skt))
            print("ama_th th0 amazon msg received: " + str(msg))
            # put acks from amazon to set
            with mutex:
                for ack in msg.acks:
                    ack_from_ama.add(ack)
                    print("ama th0 ack received: " + str(ack))
            """
            mutex.acquire()
            for ack in msg.acks:
                ack_from_ama.add(ack)
                print("ama th0 ack received: " + str(ack))
            mutex.release()
            """

            for asend_truck in msg.asendtruck:
                tmp_seq = asend_truck.seq
                with seq_from_ama_lock:
                    if not tmp_seq in seq_from_ama:
                        msg_from_ama.put(asend_truck)
                        seq_from_ama.add(tmp_seq)

                umsg = IG1_pb2.UMsg()
                umsg.acks.append(asend_truck.seq)
                send_msg_str_to_ama(umsg.SerializeToString(), ama_skt)
                print("ama th0 asendtruck received: " + str(asend_truck))
            for afinish_loading in msg.afinishloading:
                tmp_seq = afinish_loading.seq
                with seq_from_ama_lock:
                    if not tmp_seq in seq_from_ama:
                        msg_from_ama.put(afinish_loading)
                        seq_from_ama.add(tmp_seq)

                umsg = IG1_pb2.UMsg()
                umsg.acks.append(afinish_loading.seq)
                send_msg_str_to_ama(umsg.SerializeToString(), ama_skt)
                print("ama th0 afinishloading received: " + str(afinish_loading))

    # world notify truck arrived warehouse
    def deal_truck_arrive_warehouse(self, msg):
        # update truck status to be "arrivewarehouse"  &  pkg productStatus to be "Delivering"
        cmd_truck = "UPDATE ups_truck SET \"truckStatus\" = 'arrivewarehouse',\"truckX\"= " + str(msg.x)\
                    + ",\"truckY\"=" + str(msg.y) + " where \"truckId\" = " \
                    + str(msg.truckid) + ";"
        cmd_pkg = "UPDATE ups_package SET \"productStatus\" = 'loading_on_truck' where \"truckId\" = " \
                  + str(msg.truckid) + ";"
        execute_cmds(self.connection, [cmd_pkg, cmd_truck])

        # put UTruckArrived on to_send
        truck_arrived_msg = IG1_pb2.UTruckArrived(truckid=msg.truckid, seq=self.fetch_seq_and_inc())
        to_send.put(truck_arrived_msg)

    def deal_truck_finish_deliver(self, msg):
        # update truck status to be "idle"
        cmd_truck = "UPDATE ups_truck SET \"truckStatus\" = 'idle',\"truckX\"=" + str(msg.x) + ", \"truckY\"=" \
                    + str(msg.y) + " where \"truckId\" = " + str(msg.truckid) + ";"
        execute_cmds(self.connection, [cmd_truck])

    def deal_pkg_delivered(self, msg):
        # update pkg productStatus to be "Delivered"
        cmd_pkg = "UPDATE ups_package SET \"productStatus\" = 'delivered', \"truckId\"=-1 where \"pkgId\" = " + str(msg.packageid) + ";"
        execute_cmds(self.connection, [cmd_pkg])

        pkg_sent = IG1_pb2.UPkgDelivered(pkgid=msg.packageid, seq=self.fetch_seq_and_inc())
        to_send.put(pkg_sent)

    # put UInitialWorld into to_send
    def deal_uconnected(self, msg):
        ini_world = IG1_pb2.UInitialWorld(worldid=msg.worldid, seq=self.fetch_seq_and_inc())
        to_send.put(ini_world)
        print("ama_th worldid from world_thread: " + str(msg.worldid))

    # th1 responsible for read from in_q, update DB or put MSG on to_send
    def th1(self):
        while not self.th1_quit:
            if not self.in_q.empty():
                msg = self.in_q.get()
                print("***********")
                print("in_q get msg: " + str(msg))
                print("***********")
                if isinstance(msg, world_ups_pb2.UFinished):
                    if msg.status == 'ARRIVE WAREHOUSE':
                        self.deal_truck_arrive_warehouse(msg)
                    elif msg.status == 'IDLE':
                        self.deal_truck_finish_deliver(msg)
                elif isinstance(msg, world_ups_pb2.UDeliveryMade):
                    self.deal_pkg_delivered(msg)
                elif isinstance(msg, world_ups_pb2.UResponses):
                    if msg.HasField('finished'):   # the end
                        self.th0_quit = True
                        self.th1_quit = True
                        self.th2_quit = True
                        self.th3_quit = True
                elif isinstance(msg, world_ups_pb2.UConnected):
                    self.deal_uconnected(msg)
                elif isinstance(msg, world_ups_pb2.UErr):
                    print("ERROR OCCURRED: ")
                    print(msg)

    # return truckid of first idle truck
    def find_idle_truck(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT \"truckId\" FROM ups_truck WHERE \"truckStatus\" = 'idle';")
        res = cursor.fetchall()
        print("find_idle_truck result: " + str(res))
        if len(res) > 0:
            return res[0][0]
        return -1

    # helping deal with asend_truck
    def asend_truck_helper(self, msg):
        upsid = "' ',"
        if msg.HasField('upsid'):
            # check auth_user if this upsid existed, if not, keep using " "
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM auth_user where username = '" + str(msg.upsid) + "'")
            res = cursor.fetchall()
            if len(res) != 0:
                upsid = "'" + msg.upsid + "'" + ','
        while True:
            idle_truck_id = self.find_idle_truck()
            if idle_truck_id != -1:
                # update package DB
                cmd_insert_pkg = "INSERT INTO ups_package (\"pkgId\",\"whId\",\"whX\",\"whY\",\"buyerX\",\"buyerY\"," \
                                 "\"upsId\",\"truckId\",\"productStatus\") VALUES (" + str(msg.pkgid) + ',' \
                                 + str(msg.whinfo.whid) + ',' + str(msg.whinfo.x) + ',' + str(msg.whinfo.y) + ',' \
                                 + str(msg.x) + ',' + str(msg.y) + ',' + upsid + str(idle_truck_id) \
                                 + ',' + "'waiting_for_pickup');"
                execute_cmds(self.connection, [cmd_insert_pkg])
                # update product DB
                cmds = []
                for product in msg.products:
                    cmd_insert_product = "insert into ups_product (\"productId\", \"productDescrip\", \"productCount\", " \
                                         "\"package_id\") values(" + str(product.id) + ",'" + product.description + "'," \
                                         + str(product.count) + "," + str(msg.pkgid) + ");"
                    cmds.append(cmd_insert_product)
                execute_cmds(self.connection, cmds)
                # update truck DB
                cmd_truck_pkgid = "update ups_truck set \"pkgId\" = " + str(msg.pkgid) + ",\"truckStatus\"='traveling'"\
                                  + " where \"truckId\" = " + str(idle_truck_id) + ";"
                execute_cmds(self.connection, [cmd_truck_pkgid])

                # put msg to out_q
                gopickup_msg = world_ups_pb2.UGoPickup(truckid=idle_truck_id, whid=msg.whinfo.whid,
                                                       seqnum=self.fetch_seq_and_inc())
                self.out_q.put(gopickup_msg)
                print("asend_truck_helper put gopickup_msg to out_q: " + str(gopickup_msg))

                # put ack & UOrderPlaced onto to_send
                put_ack_umsg(msg.seq)
                uorder_placed_msg = IG1_pb2.UOrderPlaced(pkgid=msg.pkgid, truckid=idle_truck_id,
                                                         seq=self.fetch_seq_and_inc())
                to_send.put(uorder_placed_msg)
                print("asend_truck_helper put uorder_placed_msg on to_send: " + str(uorder_placed_msg))
                break

    def deal_asendtruck(self, msg):
        new_th5 = threading.Thread(target=self.asend_truck_helper, args=(msg,))
        new_th5.start()

    def deal_afinishloading(self, msg):
        # update DB
        cmd_pkg = "update ups_package set \"productStatus\"='delivering' where \"pkgId\"=" + str(msg.pkgid) + ";"
        execute_cmds(self.connection, [cmd_pkg])

        # put UGoDeliver on out_q
        cursor = self.connection.cursor()
        cursor.execute("select \"buyerX\",\"buyerY\" from ups_package where \"pkgId\"=" + str(msg.pkgid) + ";")
        res = cursor.fetchall()
        godeliver_msg = world_ups_pb2.UGoDeliver(truckid=msg.truckid,
                                                 packages=[world_ups_pb2.UDeliveryLocation(packageid=msg.pkgid,
                                                                                           x=res[0][0], y=res[0][1])],
                                                 seqnum=self.fetch_seq_and_inc())
        self.out_q.put(godeliver_msg)

        # put ack on to_send
        put_ack_umsg(msg.seq)

    # th2 responsible for fetching from msg_from_ama & do corresponding tasks
    def th2(self):
        while not self.th2_quit:
            if not msg_from_ama.empty():
                msg = msg_from_ama.get()
                print("************")
                print("ama_th th2 MSG read from ama: " + str(msg))
                print("************")
                if isinstance(msg, IG1_pb2.ASendTruck):
                    self.deal_asendtruck(msg)
                else:   # AFinishLoading
                    self.deal_afinishloading(msg)

    # th3 responsible for sending ack & create th4 for sending msg to amazon
    def th3(self, ama_skt):
        while not self.th3_quit:
            if not to_send.empty():
                msg = to_send.get()
                umsg = IG1_pb2.UMsg()
                if isinstance(msg, IG1_pb2.UMsg):    # only ack inside
                    send_msg_str_to_ama(msg.SerializeToString(), ama_skt)
                else:
                    if isinstance(msg, IG1_pb2.UOrderPlaced):
                        order_placed = umsg.uorderplaced.add()
                        order_placed.CopyFrom(msg)
                        print("UOrderedPlaced ready to send, truckid: " + str(msg.truckid) + " pkgid: " + str(msg.pkgid))
                    elif isinstance(msg, IG1_pb2.UTruckArrived):
                        truck_arrived = umsg.utruckarrived.add()
                        truck_arrived.CopyFrom(msg)
                        print("UTruckArrived ready to send, truckid: " + str(msg.truckid))
                    elif isinstance(msg, IG1_pb2.UPkgDelivered):
                        pkg_delivered = umsg.upkgdelivered.add()
                        pkg_delivered.CopyFrom(msg)
                        print("UPkgDelivered ready to send, pkgid: " + str(msg.pkgid))
                    elif isinstance(msg, IG1_pb2.UInitialWorld):
                        umsg.initworld.CopyFrom(msg)
                        print("UInitialWorld ready to send, with worldid: " + str(msg.worldid))
                    # else:     # only one ack inside
                    #     umsg.CopyFrom(msg)
                    send_th = threading.Thread(target=self.th4, args=(ama_skt, umsg, msg.seq))
                    send_th.start()

    # th4 responsible for sending msg only
    def th4(self, ama_skt, msg, seq):
        while True:
            send_msg_str_to_ama(msg.SerializeToString(), ama_skt)
            time.sleep(2)

            with mutex:
                if seq in ack_from_ama:
                    print("ama_th th4 ack received: " + str(seq))
                    ack_from_ama.remove(seq)
                    print("ama_th th4 send msg successfully" + str(msg))
                    break
            """
            mutex.acquire()
            if seq in ack_from_ama:
                print("ama_th th4 ack received: " + str(seq))
                ack_from_ama.remove(seq)
                print("ama_th th4 send msg successfully" + str(msg))
                break
            mutex.release()
            """



    def run(self):
        try:
            self.connection = psycopg2.connect(user='mqlyyayc', password='qSxcvkfQHBr9DfvQ-CpG-VtExKZK2v0f',
                                   host='drona.db.elephantsql.com', port='5432', database='mqlyyayc')

            ama_skt, ama_addr = self.accept_ama()

            recv_thread = threading.Thread(target=self.th0, args=(ama_skt,))
            fetch_amamsg_thread = threading.Thread(target=self.th2)
            send_thread = threading.Thread(target=self.th3, args=(ama_skt,))
            read_inq_thread = threading.Thread(target=self.th1)

            recv_thread.start()
            fetch_amamsg_thread.start()
            send_thread.start()
            read_inq_thread.start()

            recv_thread.join()
            fetch_amamsg_thread.join()
            send_thread.join()
            read_inq_thread.join()
        except (Exception, psycopg2.Error) as error:
            print("Error while connecting to PostgreSQL", error)
        finally:
            if self.connection:
                self.connection.close()
