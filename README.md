# Mini Ups

Constructed web app with separate tiers (UI, server and database), provide online delivering management service 
Set up UI tier with Django to receive requests from users and interact with server and database logically 
Assigned server tier to communicate with a real-world simulator to access trucks for Ups and delivering information, and our partner group set up an Amazon server to provide online shopping experience. 
Synchronized and stored data by providing a cloud Postgres database shared between UI and server

![avatar](https://upload.wikimedia.org/wikipedia/commons/1/1b/UPS_Logo_Shield_2017.svg)

```
For the website frontend and backend we use Django
For the program used to communicate with Amazon and World, we use python
```

To run the website:

```
cd mysite
python3 manage.py runserver 0.0.0.0:8000
```

To run the program to establish communication with world and Amazon:

```
cd Ups
python3 upsCommunicator.py <worldIp> 12345
```
worldIp is the Ip of the environment where world is running on
