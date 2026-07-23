//+------------------------------------------------------------------+
//|                                            NeroFlowStreamer.mq5  |
//|                                  Copyright 2026, NERO FLOW Corp  |
//|                                             https://neroflow.io  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, NERO FLOW"
#property link      "https://neroflow.io"
#property version   "2.10"

//--- inputs
input group "=== Server Config ==="
input string   InpServerUrl      = "https://orderflow-production-0e8e.up.railway.app"; // رابط السيرفر على Railway
input string   InpSecretKey      = "MySecretKey123";       // رمز التحقق والأمان للبوابة

input group "=== Market Config ==="
input string   InpSymbol         = "XAUUSD";                // رمز الأصل المراد تتبعه
input string   InpClientId       = "CDPFXAUUSD1";          // ClusterDelta Client ID
input bool     InpAutoDetectClientId = false;              // Auto Detect Client ID (F3 list)


//--- DLL imports from ClusterDelta
#import "footprint_v1x0_x64.dll"
string Footprint_Data(int &length, string client_id);
int Footprint_Subscribe(int &k, string client_id, string symbol, int timeframe, string time_curr, string time_last_bar, string futures_name, string time_last_loaded, string gmt, string ver, int range_id, string start_time, string end_time, string company, int account);
#import

//--- structures for cache
struct PriceCache
{
   double price;
   long   ask;
   long   bid;
};

//--- global variables
PriceCache g_price_cache[];
int        g_cache_size = 0;
string     g_current_candle_time = "";
string     g_last_post_status = "Initializing...";

// indicator handles
int g_handle_icustom    = INVALID_HANDLE;
int g_handle_footprint  = INVALID_HANDLE;
int g_handle_ema10      = INVALID_HANDLE;
int g_handle_ema34      = INVALID_HANDLE;
int g_handle_ema50      = INVALID_HANDLE;

string g_client_id = "";
string g_futures_name = "";
int    g_subscribe_k = 0;

//+------------------------------------------------------------------+
//| Custom helper functions                                          |
//+------------------------------------------------------------------+
string GetFuturesName(string symbol)
{
   if(StringFind(symbol, "EUR") >= 0) return "6E";
   if(StringFind(symbol, "GBP") >= 0) return "6B";
   if(StringFind(symbol, "JPY") >= 0) return "6J";
   if(StringFind(symbol, "CAD") >= 0) return "6C";
   if(StringFind(symbol, "AUD") >= 0) return "6A";
   if(StringFind(symbol, "CHF") >= 0) return "6S";
   if(StringFind(symbol, "XAU") >= 0 || StringFind(symbol, "GOLD") >= 0) return "GC";
   if(StringFind(symbol, "XAG") >= 0 || StringFind(symbol, "SILVER") >= 0) return "SI";
   return "GC"; // default to Gold
}

void ResetCache()
{
   g_cache_size = 0;
   ArrayResize(g_price_cache, 0);
}

void UpdateCacheAndGetDiff(double price, long current_ask, long current_bid, long &diff_ask, long &diff_bid)
{
   diff_ask = 0;
   diff_bid = 0;
   
   int found_idx = -1;
   for(int i=0; i<g_cache_size; i++)
   {
      if(NormalizeDouble(g_price_cache[i].price - price, 5) == 0.0)
      {
         found_idx = i;
         break;
      }
   }
   
   if(found_idx >= 0)
   {
      diff_ask = current_ask - g_price_cache[found_idx].ask;
      diff_bid = current_bid - g_price_cache[found_idx].bid;
      
      if(diff_ask < 0) diff_ask = 0;
      if(diff_bid < 0) diff_bid = 0;
      
      g_price_cache[found_idx].ask = current_ask;
      g_price_cache[found_idx].bid = current_bid;
   }
   else
   {
      g_cache_size++;
      ArrayResize(g_price_cache, g_cache_size);
      g_price_cache[g_cache_size - 1].price = price;
      g_price_cache[g_cache_size - 1].ask = current_ask;
      g_price_cache[g_cache_size - 1].bid = current_bid;
      
      diff_ask = current_ask;
      diff_bid = current_bid;
   }
}

//+------------------------------------------------------------------+
//| Update visual dashboard on chart                                 |
//+------------------------------------------------------------------+
void UpdateDashboard(double volume, double ask, double bid, double delta, double delta_pos, double delta_neg)
{
   string text = "";
   text += "╔══════════════════════════════════════════════════════╗\n";
   text += "║                 NERO FLOW GATEWAY v2.10              ║\n";
   text += "╠══════════════════════════════════════════════════════╣\n";
   text += "  [•] Status:      " + g_last_post_status + "\n";
   text += "  [•] Symbol:      " + _Symbol + " (" + g_futures_name + " Futures)\n";
   text += "  [•] Server URL:  " + InpServerUrl + "\n";
   text += "  [•] Client ID:   " + g_client_id + "\n";
   text += "  [•] Cache Size:  " + IntegerToString(g_cache_size) + " price levels\n";
   text += "  [•] Candle Time: " + g_current_candle_time + "\n";
   text += "╠══════════════════════════════════════════════════════╣\n";
   text += "  [📥 ClusterDelta Indicator Live Values]\n";
   text += "  - Volume:  " + DoubleToString(volume, 1) + "\n";
   text += "  - Ask Vol: " + DoubleToString(ask, 1) + "\n";
   text += "  - Bid Vol: " + DoubleToString(bid, 1) + "\n";
   text += "  - Delta:   " + DoubleToString(delta, 1) + "\n";
   text += "  - Delta+:  " + DoubleToString(delta_pos, 1) + "\n";
   text += "  - Delta-:  " + DoubleToString(delta_neg, 1) + "\n";
   text += "╚══════════════════════════════════════════════════════╝\n";
   
   Comment(text);
}

//+------------------------------------------------------------------+
//| Load Indicator Helper with Fallback                             |
//+------------------------------------------------------------------+
int LoadIndicatorHandle(string short_name)
{
   // 1. Try loading from root Indicators folder
   ResetLastError();
   int handle = iCustom(InpSymbol, _Period, short_name);
   if(handle != INVALID_HANDLE)
   {
      Print("✅ Loaded indicator from root folder: ", short_name);
      return handle;
   }
   
   // 2. Try loading from 'ClusterDelta' subfolder
   ResetLastError();
   handle = iCustom(InpSymbol, _Period, "ClusterDelta\\" + short_name);
   if(handle != INVALID_HANDLE)
   {
      Print("✅ Loaded indicator from ClusterDelta folder: ", short_name);
      return handle;
   }
       
   // 3. Try loading from 'Free Indicators' subfolder as fallback
   ResetLastError();
   handle = iCustom(InpSymbol, _Period, "Free Indicators\\" + short_name);
   if(handle != INVALID_HANDLE)
   {
      Print("✅ Loaded indicator from Free Indicators: ", short_name);
      return handle;
   }
   
   Print("❌ Failed to load indicator '", short_name, "' from root, ClusterDelta, or Free Indicators. Error: ", GetLastError());
   return INVALID_HANDLE;
}

int LoadDevelopersIndicatorHandle(string short_name)
{
   ResetLastError();
   int handle = iCustom(InpSymbol, _Period, short_name,
      "https://clusterdelta.com/ab-over-v", // HELP_URL
      "GC->XAUUSD*Gold",                    // Instrument as Data Source
      "AUTO",                               // MetaTrader_GMT
      "",                                   // Comment_Layers
      true,                                 // Volume_Layer
      true,                                 // AskBid_Layer
      true,                                 // Delta_Layer
      "",                                   // Comment_History
      0,                                    // Days_in_History
      D'2017.01.01 00:00:00',               // Custom_Start_date
      D'2017.01.01 00:00:00',               // Custom_End_date
      "",                                   // Reverse_Settings
      false,                                // ReverseChart
      "...for USD/JPY, USD/CAD, USD/CHF --", // DO_NOT_SET_ReverseChart
      8                                     // Font_Size
   );
   
   if(handle != INVALID_HANDLE)
   {
      Print("✅ Loaded developers indicator with parameters: ", short_name);
      return handle;
   }
   
   ResetLastError();
   handle = iCustom(InpSymbol, _Period, "ClusterDelta\\" + short_name,
      "https://clusterdelta.com/ab-over-v", // HELP_URL
      "GC->XAUUSD*Gold",                    // Instrument as Data Source
      "AUTO",                               // MetaTrader_GMT
      "",                                   // Comment_Layers
      true,                                 // Volume_Layer
      true,                                 // AskBid_Layer
      true,                                 // Delta_Layer
      "",                                   // Comment_History
      0,                                    // Days_in_History
      D'2017.01.01 00:00:00',               // Custom_Start_date
      D'2017.01.01 00:00:00',               // Custom_End_date
      "",                                   // Reverse_Settings
      false,                                // ReverseChart
      "...for USD/JPY, USD/CAD, USD/CHF --", // DO_NOT_SET_ReverseChart
      8                                     // Font_Size
   );
   
   if(handle != INVALID_HANDLE)
   {
      Print("✅ Loaded developers indicator from ClusterDelta folder with parameters: ", short_name);
      return handle;
   }
   
   return INVALID_HANDLE;
}

//+------------------------------------------------------------------+
//| Upload candle history for technical analysis and AI scans        |
//+------------------------------------------------------------------+
void UploadCandleHistory()
{
    ENUM_TIMEFRAMES periods[1];
    string period_names[1];
    
    periods[0] = _Period;
    if(_Period == PERIOD_M1) period_names[0] = "M1";
    else if(_Period == PERIOD_M5) period_names[0] = "M5";
    else return; // Only process M1 or M5
   
   for(int p = 0; p < ArraySize(periods); p++)
   {
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(InpSymbol, periods[p], 0, 300, rates);
      if(copied <= 0)
      {
         Print("⚠️ Failed to copy rates for ", period_names[p], ". History might be loading...");
         continue;
      }
      
      // Fetch indicator volume and delta if on the active timeframe
      double real_volumes[];
      double real_deltas[];
      int vol_copied = 0;
      int delta_copied = 0;
      
      double ema10_vals[];
      double ema34_vals[];
      double ema50_vals[];
      int ema10_copied = 0;
      int ema34_copied = 0;
      int ema50_copied = 0;
      
      if(periods[p] == _Period)
      {
         if(g_handle_icustom != INVALID_HANDLE)
         {
            vol_copied = CopyBuffer(g_handle_icustom, 0, 0, copied, real_volumes);
            delta_copied = CopyBuffer(g_handle_icustom, 2, 0, copied, real_deltas);
            ArraySetAsSeries(real_volumes, true);
            ArraySetAsSeries(real_deltas, true);
         }
         
         if(g_handle_ema10 != INVALID_HANDLE)
         {
            ema10_copied = CopyBuffer(g_handle_ema10, 0, 0, copied, ema10_vals);
            ArraySetAsSeries(ema10_vals, true);
         }
         if(g_handle_ema34 != INVALID_HANDLE)
         {
            ema34_copied = CopyBuffer(g_handle_ema34, 0, 0, copied, ema34_vals);
            ArraySetAsSeries(ema34_vals, true);
         }
         if(g_handle_ema50 != INVALID_HANDLE)
         {
            ema50_copied = CopyBuffer(g_handle_ema50, 0, 0, copied, ema50_vals);
            ArraySetAsSeries(ema50_vals, true);
         }
      }
      
      string json = "[";
      for(int i = 0; i < copied; i++)
      {
         double c_vol = (double)rates[i].tick_volume;
         double c_delta = 0.0;
         
         // Map index correctly (both rates and CopyBuffer are newest-first because ArraySetAsSeries is true for both)
         if(vol_copied > 0 && i < vol_copied)
         {
            c_vol = real_volumes[i];
         }
         if(delta_copied > 0 && i < delta_copied)
         {
            c_delta = real_deltas[i];
         }
         
         double c_ema10 = 0.0;
         double c_ema34 = 0.0;
         double c_ema50 = 0.0;
         if(ema10_copied > 0 && i < ema10_copied) c_ema10 = ema10_vals[i];
         if(ema34_copied > 0 && i < ema34_copied) c_ema34 = ema34_vals[i];
         if(ema50_copied > 0 && i < ema50_copied) c_ema50 = ema50_vals[i];
         
         double c_ask = (c_vol + c_delta) / 2.0;
         double c_bid = (c_vol - c_delta) / 2.0;
         
         if(i > 0) json += ",";
         json += "{\"symbol\":\"" + InpSymbol + "\",";
         json += "\"timeframe\":\"" + period_names[p] + "\",";
         json += "\"time\":\"" + TimeToString(rates[i].time, TIME_DATE|TIME_MINUTES|TIME_SECONDS) + "\",";
         json += "\"open\":" + DoubleToString(rates[i].open, _Digits) + ",";
         json += "\"high\":" + DoubleToString(rates[i].high, _Digits) + ",";
         json += "\"low\":" + DoubleToString(rates[i].low, _Digits) + ",";
         json += "\"close\":" + DoubleToString(rates[i].close, _Digits) + ",";
         json += "\"volume\":" + DoubleToString(c_vol, 1) + ",";
         json += "\"ask\":" + DoubleToString(c_ask, 1) + ",";
         json += "\"bid\":" + DoubleToString(c_bid, 1) + ",";
         json += "\"delta\":" + DoubleToString(c_delta, 1) + ",";
         json += "\"ema10\":" + DoubleToString(c_ema10, _Digits) + ",";
         json += "\"ema34\":" + DoubleToString(c_ema34, _Digits) + ",";
         json += "\"ema50\":" + DoubleToString(c_ema50, _Digits) + ",";
         json += "\"secret\":\"" + InpSecretKey + "\"}";
      }

      json += "]";
      
      string endpoint = InpServerUrl + "/api/market-data";
      string headers = "Content-Type: application/json\r\n";
      headers += "X-Gateway-Auth: " + InpSecretKey + "\r\n";
      
      char post_data[];
      char result_data[];
      string result_headers;
      StringToCharArray(json, post_data, 0, WHOLE_ARRAY, CP_UTF8);
      
      ResetLastError();
      int timeout = 5000; // 5 seconds timeout
      int response_code = WebRequest("POST", endpoint, headers, timeout, post_data, result_data, result_headers);
      Print("✅ Uploaded ", copied, " candles for ", period_names[p], ". Server Response: ", response_code);
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit()
{
   if(StringLen(InpServerUrl) == 0)
   {
      Alert("❌ NeroFlow EA Error: Server URL input parameter is empty! Please check your Inputs tab.");
      Print("❌ ERROR: Server URL is empty!");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(StringLen(InpSymbol) == 0)
   {
      Alert("❌ NeroFlow EA Error: Symbol input parameter is empty! Please check your Inputs tab.");
      Print("❌ ERROR: Symbol is empty!");
      return(INIT_PARAMETERS_INCORRECT);
   }

   g_futures_name = GetFuturesName(InpSymbol);
   
   // generate unique client id for ClusterDelta DLL registration
   if(StringLen(InpClientId) > 0 && InpClientId != "CDPFXAUUSD1")
   {
      g_client_id = InpClientId;
   }
   else
   {
      MathSrand(GetTickCount());
      g_client_id = "CDPF" + StringSubstr(IntegerToString(TimeLocal()), 7, 3) + IntegerToString(MathAbs(MathRand()) % 10);
      Print("🔑 NeroFlow: Generated unique client ID for EA: ", g_client_id);
   }

     // 1. Initialize ClusterDelta indicators via iCustom() with folder fallback
     g_handle_footprint  = LoadIndicatorHandle("#Footprint_Data_for_EA");
      g_handle_icustom    = LoadDevelopersIndicatorHandle("#Volume_AskBid_Delta_for_Developers 5.6");
      if(g_handle_icustom == INVALID_HANDLE)
      {
         g_handle_icustom = LoadDevelopersIndicatorHandle("#Volume_AskBid_Delta_for_Developers");
      }
      if(g_handle_icustom == INVALID_HANDLE)
      {
         g_handle_icustom = LoadIndicatorHandle("#Volume_Delta_EA_iCustom");
      }
     
     if(g_handle_icustom == INVALID_HANDLE)
     {
        Print("⚠️ Warning: Could not load Volume/AskBid/Delta indicator. Standard tick volume will be used.");
     }
     
     // Initialize EMAs
     g_handle_ema10 = iMA(InpSymbol, _Period, 10, 0, MODE_EMA, PRICE_CLOSE);
     g_handle_ema34 = iMA(InpSymbol, _Period, 34, 0, MODE_EMA, PRICE_CLOSE);
     g_handle_ema50 = iMA(InpSymbol, _Period, 50, 0, MODE_EMA, PRICE_CLOSE);

   if(_Period == PERIOD_M1)
   {
       g_handle_footprint  = LoadIndicatorHandle("#Footprint_Data_for_EA");
       if(g_handle_footprint == INVALID_HANDLE)
       {
          string err_msg = "Failed to load: #Footprint_Data_for_EA (" + IntegerToString(GetLastError()) + ") ";
          g_last_post_status = "ERROR: " + err_msg;
          UpdateDashboard(0,0,0,0,0,0);
          Alert("❌ NeroFlow EA Error: " + err_msg + " (Check Experts tab for logs)");
          Print("❌ ERROR: " + err_msg);
          return(INIT_FAILED);
       }

       // Subscribe to footprint dll feed
       datetime current_bar_time = 0;
       datetime times[];
       if(CopyTime(InpSymbol, _Period, 0, 1, times) > 0)
       {
          current_bar_time = times[0];
       }
       else
       {
          current_bar_time = TimeCurrent();
       }
       
       datetime last_loaded_time = TimeCurrent() - 7200; // 2 hours ago to request recent ticks
       
       ResetLastError();
       int res = Footprint_Subscribe(g_subscribe_k, g_client_id, InpSymbol, (int)_Period, TimeToString(TimeCurrent()), TimeToString(current_bar_time), g_futures_name, TimeToString(last_loaded_time), "AUTO", "5.4", 0, "", "", AccountInfoString(ACCOUNT_COMPANY), (int)AccountInfoInteger(ACCOUNT_LOGIN));
       if(res < 0)
       {
          Print("⚠️ Footprint DLL subscription returned warning (Code: ", res, ", Error: ", GetLastError(), ")");
       }
   }
   else
   {
       g_handle_footprint = INVALID_HANDLE;
   }

   EventSetMillisecondTimer(250); // timer runs every 250ms
   ResetCache();
   
   g_last_post_status = "Connected & Active";
   UpdateDashboard(0,0,0,0,0,0);
   
   Print("🚀 NeroFlow ClusterDelta Gateway Initialized. Futures Symbol: ", g_futures_name);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
    IndicatorRelease(g_handle_icustom);
    IndicatorRelease(g_handle_footprint);
    IndicatorRelease(g_handle_ema10);
    IndicatorRelease(g_handle_ema34);
    IndicatorRelease(g_handle_ema50);
   Comment(""); // clear comment on chart
   Print("🔌 NeroFlow ClusterDelta Gateway Deinitialized.");
}

//+------------------------------------------------------------------+
//| AutoDetectClientId                                               |
//+------------------------------------------------------------------+
string AutoDetectClientId()
{
   int total = GlobalVariablesTotal();
   string best_id = "";
   datetime latest_time = 0;
   
   for(int i = 0; i < total; i++)
   {
      string name = GlobalVariableName(i);
      if(StringFind(name, "CLUSTERDELTA_CDP") == 0)
      {
         datetime gv_time = GlobalVariableTime(name);
         if(gv_time > latest_time)
         {
            latest_time = gv_time;
            best_id = StringSubstr(name, 13); // remove "CLUSTERDELTA_" (13 chars)
         }
      }
   }
   
   return best_id;
}

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick()
{
   // Tick event triggers dashboard update if needed
}

//+------------------------------------------------------------------+
void OnTimer()
{
   // Determine active client ID based on settings (Only on M1 timeframe)
   if(_Period == PERIOD_M1)
   {
      string detected_id = g_client_id;
      if(InpAutoDetectClientId)
      {
         detected_id = AutoDetectClientId();
      }
      else
      {
         detected_id = InpClientId;
      }
      
      if(StringLen(detected_id) > 0 && detected_id != g_client_id)
      {
         Print("🔄 NeroFlow: Syncing ClusterDelta Client ID: ", detected_id);
         g_client_id = detected_id;
         
         // Re-subscribe with client ID
         datetime current_bar_time = 0;
         datetime times[];
         if(CopyTime(InpSymbol, _Period, 0, 1, times) > 0)
         {
            current_bar_time = times[0];
         }
         else
         {
            current_bar_time = TimeCurrent();
         }
         
         datetime last_loaded_time = TimeCurrent() - 7200; // 2 hours ago
         
         ResetLastError();
         int res = Footprint_Subscribe(g_subscribe_k, g_client_id, InpSymbol, (int)_Period, TimeToString(TimeCurrent()), TimeToString(current_bar_time), g_futures_name, TimeToString(last_loaded_time), "AUTO", "5.4", 0, "", "", AccountInfoString(ACCOUNT_COMPANY), (int)AccountInfoInteger(ACCOUNT_LOGIN));
         if(res < 0)
         {
            Print("⚠️ Footprint DLL subscription returned warning (Code: ", res, ", Error: ", GetLastError(), ")");
         }
      }
   }

   int TotalBars = iBars(InpSymbol, _Period);
   if(TotalBars <= 0) return;

   datetime LastTime[];
   if(CopyTime(InpSymbol, _Period, 0, 1, LastTime) <= 0)
   {
      Print("⚠️ NeroFlow Gateway: CopyTime failed (Error: ", GetLastError(), ")");
      return;
   }

   static datetime last_bar_time = 0;
   if(LastTime[0] != last_bar_time)
   {
      last_bar_time = LastTime[0];
      UploadCandleHistory();
   }

   // --- Post Live Prices to Server (Every 5 seconds) ---
   static datetime last_price_sent_time = 0;
   if(TimeLocal() - last_price_sent_time >= 5)
   {
      last_price_sent_time = TimeLocal();
      
      double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
      double spread = ask - bid;
      
      double ema10_val[], ema34_val[], ema50_val[];
      ArraySetAsSeries(ema10_val, true);
      ArraySetAsSeries(ema34_val, true);
      ArraySetAsSeries(ema50_val, true);
      double current_ema10 = 0.0;
      double current_ema34 = 0.0;
      double current_ema50 = 0.0;
      if(CopyBuffer(g_handle_ema10, 0, 0, 1, ema10_val) > 0) current_ema10 = ema10_val[0];
      if(CopyBuffer(g_handle_ema34, 0, 0, 1, ema34_val) > 0) current_ema34 = ema34_val[0];
      if(CopyBuffer(g_handle_ema50, 0, 0, 1, ema50_val) > 0) current_ema50 = ema50_val[0];
      
      string price_json = "{\"symbol\":\"" + InpSymbol + "\",";
      price_json += "\"bid\":" + DoubleToString(bid, _Digits) + ",";
      price_json += "\"ask\":" + DoubleToString(ask, _Digits) + ",";
      price_json += "\"spread\":" + DoubleToString(spread, _Digits) + ",";
      price_json += "\"ema10\":" + DoubleToString(current_ema10, _Digits) + ",";
      price_json += "\"ema34\":" + DoubleToString(current_ema34, _Digits) + ",";
      price_json += "\"ema50\":" + DoubleToString(current_ema50, _Digits) + ",";
      price_json += "\"server_time\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES|TIME_SECONDS) + "\",";
      price_json += "\"secret\":\"" + InpSecretKey + "\"}";
      
      string endpoint = InpServerUrl + "/api/live-prices";
      string headers = "Content-Type: application/json\r\n";
      headers += "X-Gateway-Auth: " + InpSecretKey + "\r\n";
      
      char post_data[];
      char result_data[];
      string result_headers;
      StringToCharArray(price_json, post_data, 0, WHOLE_ARRAY, CP_UTF8);
      
      int timeout = 2000; // safe timeout
      WebRequest("POST", endpoint, headers, timeout, post_data, result_data, result_headers);
   }

   // Force MT5 to calculate the footprint indicator by copying at least one element from it
   if(g_handle_footprint != INVALID_HANDLE)
   {
      double dummy_footprint[];
      CopyBuffer(g_handle_footprint, 0, 0, 1, dummy_footprint);
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   CopyRates(InpSymbol, _Period, 0, 1, rates);

    double dev_volumes[];
    double dev_deltas[];

    double ind_volume = (double)rates[0].tick_volume;
    double ind_delta = 0.0;
    double ind_ask = ind_volume / 2.0;
    double ind_bid = ind_volume / 2.0;
    double ind_delta_pos = 0.0;
    double ind_delta_neg = 0.0;

    if(g_handle_icustom != INVALID_HANDLE)
    {
       if(CopyBuffer(g_handle_icustom, 0, 0, 1, dev_volumes) > 0 &&
          CopyBuffer(g_handle_icustom, 2, 0, 1, dev_deltas) > 0)
       {
          ind_volume = dev_volumes[0];
          ind_delta = dev_deltas[0];
          ind_ask = (ind_volume + ind_delta) / 2.0;
          ind_bid = (ind_volume - ind_delta) / 2.0;
          ind_delta_pos = (ind_delta > 0) ? ind_delta : 0.0;
          ind_delta_neg = (ind_delta < 0) ? -ind_delta : 0.0;
       }
       else
       {
          static bool warning_printed = false;
          if(!warning_printed)
          {
             Print("ℹ️ Volume indicator data not yet computed by MT5. Streaming ticks fallback active.");
             warning_printed = true;
          }
       }
    }

    // 🧪 Diagnostics for ClusterDelta Developers Indicator Buffers (Checking all 8 buffers)
    if(g_handle_icustom != INVALID_HANDLE)
    {
       string dbg_msg = "🧪 [BUFFERS DIAGNOSTIC] ";
       for(int b = 0; b < 8; b++)
       {
          double temp_buf[];
          int r = CopyBuffer(g_handle_icustom, b, 0, 1, temp_buf);
          dbg_msg += "Buf" + IntegerToString(b) + ": r=" + IntegerToString(r) + " v=" + ((r > 0) ? DoubleToString(temp_buf[0], 1) : "-1") + " | ";
       }
       Print(dbg_msg);
    }
    else
    {
       Print("🧪 [INDICATOR DIAGNOSTIC] Handle is INVALID_HANDLE! Indicator is not loaded.");
    }

   // Update chart dashboard
   UpdateDashboard(ind_volume, ind_ask, ind_bid, ind_delta, ind_delta_pos, ind_delta_neg);

   // --- AUDIT LOGGER: STAGE 1 & 2 - Indicator Buffer Mapping & Real Time Values ---
   static datetime last_audit_time = 0;
   bool run_audit = (TimeCurrent() - last_audit_time >= 10); // Print audit details every 10 seconds to keep log readable
   if(run_audit)
   {
      last_audit_time = TimeCurrent();
      Print("==========================================================================================");
      Print("🔍 [ORDER FLOW DATA AUDIT] Starting full pipeline verification trace...");
      Print("1. Indicator Extraction mapping:");
      Print("   -> Volume        <- Indicator: #Volume_AskBid_Delta_for_Developers -> Buffer [0 or 2]");
      Print("   -> Delta         <- Indicator: #Volume_AskBid_Delta_for_Developers -> Buffer [3]");
      Print("   -> Ask Volume    <- Extracted directly from Indicator Buffer [1]");
      Print("   -> Bid Volume    <- Extracted directly from Indicator Buffer [2]");
      Print("   -> Positive Delta<- Calculated: (Delta > 0) ? Delta : 0");
      Print("   -> Negative Delta<- Calculated: (Delta < 0) ? -Delta : 0");
      Print("2. Extracted Indicator values:");
      Print("   * Raw Volume: ", DoubleToString(ind_volume, 1));
      Print("   * Raw Delta: ", DoubleToString(ind_delta, 1));
      Print("   * Calculated Ask Volume: ", DoubleToString(ind_ask, 1));
      Print("   * Calculated Bid Volume: ", DoubleToString(ind_bid, 1));
      Print("   * Positive Delta: ", DoubleToString(ind_delta_pos, 1));
      Print("   * Negative Delta: ", DoubleToString(ind_delta_neg, 1));
   }

   // 2. Fetch footprint data from shared file (Only on M1 and M5)
   if(_Period == PERIOD_M1 || _Period == PERIOD_M5)
   {
      string file_name = (_Period == PERIOD_M1) ? "footprint_stream_M1.txt" : "footprint_stream_M5.txt";
      string tf_label = (_Period == PERIOD_M1) ? "M1" : "M5";
      
      string ts_stream = "";
      if(FileIsExist(file_name, FILE_COMMON))
      {
         int file_handle = FileOpen(file_name, FILE_READ|FILE_TXT|FILE_COMMON);
         if(file_handle != INVALID_HANDLE)
         {
            while(!FileIsEnding(file_handle))
            {
               ts_stream += FileReadString(file_handle) + "\n";
            }
             FileClose(file_handle);
             FileDelete(file_name, FILE_COMMON);
             Print("📖 [EA] Read ", tf_label, " footprint file. Size: ", StringLen(ts_stream));
         }
      }
      
      if(StringLen(ts_stream) == 0)
      {
         if(run_audit)
         {
            Print("3. Shared Footprint File: Empty (No new ticks written by indicator for ", tf_label, ").");
            Print("==========================================================================================");
         }
         return; // no new footprint stream data
      }

      // Escape newlines for JSON string safety
      string escaped_stream = ts_stream;
      StringReplace(escaped_stream, "\n", "\\n");
      StringReplace(escaped_stream, "\r", "");

      string json = "{\"symbol\":\"" + InpSymbol + "\",";
      json += "\"timeframe\":\"" + tf_label + "\",";
      json += "\"raw_data\":\"" + escaped_stream + "\"}";

      string endpoint = InpServerUrl + "/api/live-footprint";
      string headers = "Content-Type: application/json\r\n";
      headers += "X-Gateway-Auth: " + InpSecretKey + "\r\n";

      char post_data[];
      char result_data[];
      string result_headers;
      StringToCharArray(json, post_data, 0, WHOLE_ARRAY, CP_UTF8);

      ResetLastError();
      int timeout = 2000;
      int response_code = WebRequest("POST", endpoint, headers, timeout, post_data, result_data, result_headers);
      
      if(response_code != 200)
      {
         g_last_post_status = "Footprint Post Failed (" + IntegerToString(response_code) + ")";
         Print("⚠️ NeroFlow Gateway: Footprint POST failed (Code: ", response_code, ", Error: ", GetLastError(), ")");
      }
      else
      {
         g_last_post_status = "Streaming Footprint... (OK)";
      }
   }
}
