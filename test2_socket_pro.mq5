
// test2_socket_pro.mq5
// Upgrade version: MT5 <-> Python bidirectional socket bridge

#import "ws2_32.dll"
int socket(int af,int type,int protocol);
int connect(int s,uchar &name[],int namelen);
int send(int s,uchar &buf[],int len,int flags);
int recv(int s,uchar &buf[],int len,int flags);
int closesocket(int s);
#import

int py_socket = -1;

//--------------------------------

bool ConnectPython()
{
   py_socket = socket(2,1,6);

   uchar addr[16];

   addr[0]=2;
   addr[1]=0;

   addr[2]=0x23;
   addr[3]=0x82;

   addr[4]=127;
   addr[5]=0;
   addr[6]=0;
   addr[7]=1;

   int res = connect(py_socket,addr,16);

   if(res==0)
   {
      Print("Connected to Python bridge");
      return true;
   }

   Print("Socket connection failed");
   return false;
}

//--------------------------------

void SendJSON(string json)
{

   if(py_socket < 0)
      return;

   uchar data[];
   StringToCharArray(json,data);

   send(py_socket,data,ArraySize(data),0);
}

//--------------------------------

void SendPrice()
{

   double price = SymbolInfoDouble(_Symbol,SYMBOL_BID);

   string msg = "{"
   "\"type\":\"price\","
   "\"price\":"+DoubleToString(price,5)+","
   "\"tf\":\"M1\""
   "}";

   SendJSON(msg);
}

//--------------------------------

void SendCandle()
{

   string msg = "{"
   "\"type\":\"candle\","
   "\"data\":{"
   "\"time\":"+IntegerToString(Time[0])+","
   "\"open\":"+DoubleToString(Open[0],5)+","
   "\"high\":"+DoubleToString(High[0],5)+","
   "\"low\":"+DoubleToString(Low[0],5)+","
   "\"close\":"+DoubleToString(Close[0],5)+""
   "}}";

   SendJSON(msg);
}

//--------------------------------

void CheckPythonCommand()
{

   uchar buf[512];

   int r = recv(py_socket,buf,512,0);

   if(r<=0)
      return;

   string msg = CharArrayToString(buf);

   if(StringFind(msg,"BUY")>=0)
   {
      Print("Python BUY signal received");
      // Place your buy logic here
   }

   if(StringFind(msg,"SELL")>=0)
   {
      Print("Python SELL signal received");
      // Place your sell logic here
   }

}

//--------------------------------

int OnInit()
{

   ConnectPython();

   return(INIT_SUCCEEDED);

}

//--------------------------------

void OnTick()
{

   SendPrice();
   SendCandle();

   CheckPythonCommand();

}
