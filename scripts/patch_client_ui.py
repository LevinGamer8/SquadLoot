from pathlib import Path
p=Path(__file__).resolve().parents[1]/'SquadLoot-Windows-Client'/'app.py'
s=p.read_text(encoding='utf-8')
s=s.replace('"""SquadLoot 1.1 - desktop UI, private replay sync and safe update staging."""','"""SquadLoot 1.3 - modern rounded desktop UI and optional lightweight live estimate."""')
s=s.replace("BG='#09111f'", "BG='#090f19'")
s=s.replace("SIDE='#0d1a2a'", "SIDE='#0d1726'")
s=s.replace("CARD='#111f32'", "CARD='#142339'")
s=s.replace("CARD2='#172a42'", "CARD2='#1a3049'")
s=s.replace("LINE='#28425c'", "LINE='#2d4866'")
s=s.replace("TEXT='#edf6ff'", "TEXT='#f0f8ff'")
s=s.replace("MUTED='#90a5bb'", "MUTED='#9fb4cc'")
s=s.replace("CYAN='#56c7ef'", "CYAN='#70d7ff'")
s=s.replace("GREEN='#67deb0'", "GREEN='#7ae5ba'")
s=s.replace("AMBER='#efc46a'", "AMBER='#ffc87c'")
s=s.replace("BUTTON='#1a3755'", "BUTTON='#223b56'")
s=s.replace("ACCENT='#116ca4'", "ACCENT='#176ca9'")
# Insert widgets after colors, before Gui.
needle="ACCENT='#176ca9'\n\n\nclass Gui:"
widget='''ACCENT='#176ca9'


def rounded_rect(canvas, x1, y1, x2, y2, radius, color, outline=None, width=1):
    """Draw a rounded rectangle without external GUI dependencies."""
    r = max(1, min(radius, (x2-x1)/2, (y2-y1)/2))
    pts = [x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,
           x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1]
    return canvas.create_polygon(pts,smooth=True,splinesteps=24,fill=color,
                                 outline=outline or color,width=width)


class RoundedCard(tk.Frame):
    """Card with a gently rounded canvas-backed border and normal Tk content."""
    def __init__(self,parent,fill=CARD,**kwargs):
        super().__init__(parent,bg=BG,bd=0,highlightthickness=0,**kwargs)
        self.fill=fill
        self.back=tk.Canvas(self,bg=BG,bd=0,highlightthickness=0)
        self.back.place(x=0,y=0,relwidth=1,relheight=1)
        self.body=tk.Frame(self,bg=fill,bd=0)
        self.body.pack(fill='both',expand=True,padx=12,pady=12)
        self.body.lift(self.back)
        self.bind('<Configure>',self._paint)

    def _paint(self,event=None):
        self.back.delete('all')
        w,h=self.winfo_width(),self.winfo_height()
        if w>=30 and h>=30:
            rounded_rect(self.back,2,2,w-2,h-2,18,self.fill,LINE)


class RoundedButton(tk.Canvas):
    """Native Tk action with softer, rounded corners; no GUI framework required."""
    def __init__(self,parent,title,command,primary=False,soft=False):
        width=max(112,int(len(title)*7.8+36))
        super().__init__(parent,width=width,height=41,bg=parent.cget('bg'),
                         bd=0,highlightthickness=0,cursor='hand2',takefocus=1)
        self._command=command;self._title=title;self._primary=primary;self._soft=soft
        self._disabled=False;self._hover=False
        self.bind('<Configure>',lambda e:self._paint())
        self.bind('<Enter>',lambda e:self._sethover(True))
        self.bind('<Leave>',lambda e:self._sethover(False))
        self.bind('<Button-1>',lambda e:self._click())
        self.bind('<Return>',lambda e:self._click())
        self.bind('<space>',lambda e:self._click())
        self._paint()

    def _sethover(self,hover):self._hover=hover;self._paint()
    def _click(self):
        if not self._disabled:self._command()
    def configure(self,cnf=None,**kwargs):
        if 'state' in kwargs:
            self._disabled=kwargs.pop('state')=='disabled'
            self._paint()
        return super().configure(cnf,**kwargs)
    config=configure
    def _paint(self):
        self.delete('all')
        w,h=max(12,self.winfo_width()),max(12,self.winfo_height())
        base=ACCENT if self._primary else (CARD2 if self._soft else BUTTON)
        fill=('#247eb7' if self._primary else '#2a4b6a') if self._hover else base
        if self._disabled:fill='#223047'
        stroke='#4a96ca' if self._primary else '#345371'
        rounded_rect(self,1,1,w-1,h-1,12,fill,stroke)
        self.create_text(w/2,h/2,text=self._title,fill=MUTED if self._disabled else TEXT,
                         font=('Segoe UI',10,'bold'))


class Gui:'''
assert needle in s
s=s.replace(needle,widget)
s=s.replace("        self.root.geometry('1130x780')", "        self.root.geometry('1210x820')")
s=s.replace("        self.root.minsize(940,680)","        self.root.minsize(1030,710)")
start=s.index('    def surface(self,parent,**kwargs):')
end=s.index('    def build(self):',start)
s=s[:start]+'''    def surface(self,parent,**kwargs):
        return RoundedCard(parent,**kwargs)

    def action(self,parent,title,callback,primary=False,soft=False,**opts):
        return RoundedButton(parent,title,callback,primary=primary,soft=soft)

'''+s[end:]
# Change card content parents from outer card to its inner content. Existing Tk packs remain intact.
replacements={
"top=tk.Frame(box,bg=CARD,padx=15,pady=12)":"top=tk.Frame(box.body,bg=CARD,padx=12,pady=7)",
"pad=tk.Frame(control,bg=CARD,padx=16,pady=14)":"pad=tk.Frame(control.body,bg=CARD,padx=9,pady=7)",
"inside=tk.Frame(team,bg=CARD,padx=16,pady=14)":"inside=tk.Frame(team.body,bg=CARD,padx=9,pady=7)",
"histinside=tk.Frame(history,bg=CARD,padx=16,pady=11)":"histinside=tk.Frame(history.body,bg=CARD,padx=9,pady=6)",
"form=tk.Frame(holder,bg=CARD,padx=20,pady=18)":"form=tk.Frame(holder.body,bg=CARD,padx=12,pady=10)",
"inside=tk.Frame(panel,bg=CARD,padx=22,pady=22)":"inside=tk.Frame(panel.body,bg=CARD,padx=12,pady=12)",
}
for a,b in replacements.items():
    assert a in s,a
    s=s.replace(a,b)
# A bit more presence on dashboard and calm navigation.
s=s.replace("self.text(brand,'SQUAD TRACKER  /  ZERO BUILD',9,True,MUTED)","self.text(brand,'ZERO BUILD  ·  SQUAD LIVE  ·  REPLAY VERIFIED',9,True,MUTED)")
s=s.replace("('live','Uebersicht'),('settings','Verbindung'),('vision','Erkennung (Beta)'),('updates','Updates')",
            "('live','◉  Dashboard'),('settings','⚙  Verbindung'),('vision','◈  Live-Erkennung'),('updates','↻  Updates')")
s=s.replace("self.page_title(page,'Dein Squad. Dein Loot.','Eine gemeinsame Runde, vier Spieler. Live-Werte sind vorlaeufig, Replays zaehlen verbindlich.')",
            "self.page_title(page,'Dein Squad. Dein Loot.','Kisten während der Runde im Blick  ·  Replay-Daten bestätigen das Ergebnis nach dem Match.')")
s=s.replace("('round','AKTUELLE RUNDE',CYAN),('squad','SQUAD-KISTEN',GREEN),",
            "('round','🧭  AKTUELLE RUNDE',CYAN),('squad','📦  SQUAD-KISTEN',GREEN),")
s=s.replace("('mine','DEIN LIVE-ZAEHLER',AMBER),('verified','REPLAY-MATCHES',CYAN)",
            "('mine','⚡  LIVE-ZÄHLER (BETA)',AMBER),('verified','✓  REPLAY-MATCHES',CYAN)")
s=s.replace("self.text(pad,'Dein Live-Tracker',14,True)","self.text(pad,'Dein Live-Tracker',15,True)")
s=s.replace("self.text(bar,'Squad in dieser Runde',14,True)","self.text(bar,'Squad in dieser Runde',15,True)")
s=s.replace("self.page_title(page,'Bildschirm-Erkennung','Experimentelles Verfahren. Ohne Spielmodifikation oder Zugriff auf den Fortnite-Prozess.')",
            "self.page_title(page,'Live-Erkennung (Beta)','Opt-in: Nur Bildschirmbereich + Interaktionstaste. Keine Fortnite-Modifikation.')")
s=s.replace("self.text(inside,'Nur die Suchaufforderung wird erkannt. Ihr Verschwinden kann auch bedeuten,\\n'\n                         'dass du dich weggedreht hast. Replays korrigieren die Schätzung spaeter.',",
            "self.text(inside,'Ein Kistenversuch wird nur geschätzt, wenn der Suchhinweis sichtbar war,\\n'\n                         'du die konfigurierte Interaktionstaste gedrückt hast und der Hinweis verschwindet.\\n'\n                         'Das ist kein sicherer Nachweis für eine geöffnete Truhe.',")
# Add key entry and performance explanation near the vision panel after row.
needle="        self.vision_var=tk.StringVar(value='Bildschirmmodus ist AUS')"
assert needle in s
s=s.replace(needle,"""        keyrow=tk.Frame(inside,bg=CARD)
        keyrow.pack(anchor='w',pady=(14,0))
        self.text(keyrow,'Interaktionstaste',10,fg=MUTED).pack(side='left',padx=(0,13))
        self.vision_key=tk.StringVar(value=self.core.config.get('interact_key','E'))
        tk.Entry(keyrow,textvariable=self.vision_key,width=4,font=('Segoe UI',12,'bold'),
                 bg='#091829',fg=TEXT,insertbackground=TEXT,relief='flat',
                 highlightbackground=LINE,highlightthickness=1).pack(side='left')
        self.text(keyrow,'1 Taste (A–Z oder 0–9), Standard E',9,fg=MUTED).pack(side='left',padx=(12,0))
        self.text(inside,'Performance-Modus: nur zentraler Bildschirmausschnitt, max. 2,5 Bilder/Sekunde,\\n'
                         'nur bei aktivem Fortnite-Fenster. Keine Bilder oder Tastendrücke werden übertragen.',
                  9,fg=MUTED,justify='left').pack(anchor='w',pady=(12,0))
        self.vision_var=tk.StringVar(value='Bildschirmmodus ist AUS')""")
old="""            self.vision=VisionDetector(self.core,self.core.config.get('vision_template',''))
            self.vision.start();self.vision_var.set('AKTIV - Schaetzung, nicht verifiziert')"""
new="""            key=self.vision_key.get().strip().upper()
            if len(key)!=1 or not key.isascii() or not key.isalnum():
                raise ValueError('Bitte genau eine Interaktionstaste A–Z oder 0–9 eintragen.')
            self.core.set_config({'interact_key':key})
            self.vision=VisionDetector(self.core,self.core.config.get('vision_template',''),key=key)
            self.vision.start();self.vision_var.set('AKTIV - vorläufige Zählung; Replay bestätigt später')"""
assert old in s
s=s.replace(old,new)
s=s.replace("self.vision_var.set(f'Aktiv / Score {self.vision.last_score:.2f} / {self.vision.count} Schaetzungen')",
            "self.vision_var.set(f'{self.vision.state}  ·  {self.vision.count} vorläufige Kisten  ·  {self.vision.perf_ms:.0f} ms/Bild')")
# Polish overlay / config copy.
s=s.replace("self.overlay.geometry('355x235+40+120')","self.overlay.geometry('390x230+40+120')")
s=s.replace("self.overlay.configure(bg=SIDE)","self.overlay.configure(bg=BG)")
s=s.replace("self.text(inside,'INSTALLIERTE VERSION',9,True,MUTED)","self.text(inside,'INSTALLIERTE VERSION',9,True,MUTED)")
p.write_text(s,encoding='utf-8')
print('patched',len(s.splitlines()),'lines')
