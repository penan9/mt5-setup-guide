//+------------------------------------------------------------------+
//|                                  Trendline_Manager_Pro_Timer     |
//+------------------------------------------------------------------+
#property strict

// --- Settings ---
input int      ButtonWidth   = 280;           
input int      ButtonHeight  = 35;
input int      X_Edge_Offset = 310;
input int      Y_Edge_Offset = 50;  
input string   Prefix        = "DL_"; 
input color    lblColor      = clrYellow;            

// Global Variables
string BtnDupName = "btn_duplicate_tl";
string BtnRemName = "btn_remove_all_tl";
string BtnExitClean = "btn_exit_clean";
string BtnExitOnly  = "btn_exit_only";
string idxLabel   = "lblNextCandle";

//+------------------------------------------------------------------+
int OnInit()
{
    CreateButton(BtnRemName,   "🗑️ Remove All",         X_Edge_Offset, Y_Edge_Offset, clrCrimson);

    CreateButton(BtnDupName,   "➕ Duplicate Selected", 
                 X_Edge_Offset, 
                 Y_Edge_Offset + (ButtonHeight + 5), 
                 clrDodgerBlue);

    CreateButton(BtnExitClean, "❌ Exit & Clean",
                 X_Edge_Offset,
                 Y_Edge_Offset + ((ButtonHeight + 5) * 2),
                 clrDarkOrange);

    CreateButton(BtnExitOnly,  "🚪 Exit Only",
                 X_Edge_Offset,
                 Y_Edge_Offset + ((ButtonHeight + 5) * 3),
                 clrDimGray);

    EventSetTimer(1); 
    return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
    ObjectDelete(0, BtnDupName);
    ObjectDelete(0, BtnRemName);
    ObjectDelete(0, BtnExitClean);
    ObjectDelete(0, BtnExitOnly);
    ObjectDelete(0, idxLabel);

    Comment(""); 
    EventKillTimer();
}

void OnTimer() { UpdateUI(); }
void OnTick()  { UpdateUI(); }

void UpdateUI()
{
    datetime lastBar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
    int tS = (int)(lastBar + PeriodSeconds() - TimeCurrent());
    if(tS < 0) tS = 0;
    string cmt = StringFormat("%02d:%02d", tS / 60, tS % 60);

    if(ObjectFind(0, idxLabel) < 0) ObjectCreate(0, idxLabel, OBJ_TEXT, 0, 0, 0);
    ObjectMove(0, idxLabel, 0, TimeCurrent() + (PeriodSeconds() * 2), SymbolInfoDouble(_Symbol, SYMBOL_BID));
    ObjectSetString(0, idxLabel, OBJPROP_TEXT, cmt);
    ObjectSetInteger(0, idxLabel, OBJPROP_COLOR, lblColor);
    ChartRedraw();
}

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
    if(id == CHARTEVENT_OBJECT_CLICK)
    {
        if(sparam == BtnDupName)
        {
            HandleDuplication();
            ObjectSetInteger(0, BtnDupName, OBJPROP_STATE, false);
        }

        if(sparam == BtnRemName)
        {
            RemoveDuplicates();
            ObjectSetInteger(0, BtnRemName, OBJPROP_STATE, false);
        }

        if(sparam == BtnExitClean)
        {
            ExitAndClean();
            ObjectSetInteger(0, BtnExitClean, OBJPROP_STATE, false);
        }

        if(sparam == BtnExitOnly)
        {
            RemoveUI();
            ObjectSetInteger(0, BtnExitOnly, OBJPROP_STATE, false);
        }

        ChartRedraw();
    }
}

void HandleDuplication()
{
    int totalSelected = 0;
    string targetName = "";

    // 1. Identify which line is currently selected
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
       string name = ObjectName(0, i);
   
       if(ObjectGetInteger(0, name, OBJPROP_TYPE) != OBJ_TREND)
           continue;
   
       if(ObjectGetInteger(0, name, OBJPROP_SELECTED))
       {
           totalSelected++;
           targetName = name;
       }
   }

    // 2. Reject if multiple lines are selected
    if(totalSelected > 1)
    {
        for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
            ObjectSetInteger(0, ObjectName(0, i), OBJPROP_SELECTED, false);
        Comment("⚠️ Error: Multiple lines selected. Unselecting all.");
        ChartRedraw();
        return;
    }

    if(totalSelected == 1)
    {
        // Capture original coordinates
        datetime t1 = (datetime)ObjectGetInteger(0, targetName, OBJPROP_TIME, 0);
        double   p1 = ObjectGetDouble(0, targetName, OBJPROP_PRICE, 0);
        datetime t2 = (datetime)ObjectGetInteger(0, targetName, OBJPROP_TIME, 1);
        double   p2 = ObjectGetDouble(0, targetName, OBJPROP_PRICE, 1);
        color    clr = (color)ObjectGetInteger(0, targetName, OBJPROP_COLOR);
        int      wid = (int)ObjectGetInteger(0, targetName, OBJPROP_WIDTH);

        // --- THE ORIGINAL STAYS ---
        // Just deselect it so it doesn't interfere
        ObjectSetInteger(0, targetName, OBJPROP_SELECTED, false);

        // --- THE DUPLICATE MOVES ---
        string copy_name = Prefix + IntegerToString(GetTickCount());
        double moveOffset = 600 * _Point; // 10 pips offset for the NEW line

        if(ObjectCreate(0, copy_name, OBJ_TREND, 0, t1, p1 + moveOffset, t2, p2 + moveOffset))
        {
            ObjectSetInteger(0, copy_name, OBJPROP_COLOR, clr);
            ObjectSetInteger(0, copy_name, OBJPROP_WIDTH, wid);
            ObjectSetInteger(0, copy_name, OBJPROP_BACK, false); 
            
            // Focus on the NEW line that shifted up
            ObjectSetInteger(0, copy_name, OBJPROP_SELECTABLE, true);
            ObjectSetInteger(0, copy_name, OBJPROP_SELECTED, true);
            
            Comment("✅ Original stays. New duplicate shifted up and selected.");
            ChartRedraw(); 
        }
    }
    else 
    {
        Comment("❌ Error: No trendline selected.");
    }
}

void RemoveDuplicates()
{
    for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, Prefix) == 0) ObjectDelete(0, name);
    }
    Comment("🗑️ Cleaned.");
}

void CreateButton(string name, string text, int x, int y, color bg)
{
    ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
    ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
    ObjectSetInteger(0, name, OBJPROP_XSIZE, ButtonWidth);
    ObjectSetInteger(0, name, OBJPROP_YSIZE, ButtonHeight);
    ObjectSetString(0, name, OBJPROP_TEXT, text);
    ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
    ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
}

void RemoveUI()
{
    ObjectDelete(0, BtnDupName);
    ObjectDelete(0, BtnRemName);
    ObjectDelete(0, BtnExitClean);
    ObjectDelete(0, BtnExitOnly);
    ObjectDelete(0, idxLabel);

    Comment("");
    EventKillTimer();

    ChartRedraw();
    
    ExpertRemove();
}

void ExitAndClean()
{
    RemoveDuplicates();
    RemoveUI();
}