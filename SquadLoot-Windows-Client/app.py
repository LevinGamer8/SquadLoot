#!/usr/bin/env python3
"""SquadLoot 1.3 - modern rounded desktop UI and optional lightweight live estimate."""
from __future__ import annotations
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox
from client_core import Core, CONFIG, chestcounter_exe, read_json, sync_once
from update_manager import current_version, check_and_stage, PENDING_FILE, log_error
from vision import VisionDetector

BG='#090f19'
SIDE='#0d1726'
CARD='#142339'
CARD2='#1a3049'
LINE='#2d4866'
TEXT='#f0f8ff'
MUTED='#9fb4cc'
CYAN='#70d7ff'
GREEN='#7ae5ba'
AMBER='#ffc87c'
RED='#ff8e92'
BUTTON='#223b56'
ACCENT='#176ca9'


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


class Gui:
    def __init__(self):
        self.core=Core()
        self.root=tk.Tk()
        self.root.title('SquadLoot - Fortnite Squad Tracker '+current_version())
        self.root.geometry('1210x820')
        self.root.minsize(1030,710)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.events=queue.Queue()
        self.overlay=None
        self.vision=None
        self.update_busy=False
        self.update_pending=False
        self.last_team=''
        self.last_history=''
        self.active=''
        self.views={}
        self.nav={}
        self.config_fields={}
        self.build()
        self.show_page('live' if self.core.config.get('server_url') else 'settings')
        self.root.after(700,self.refresh)
        self.root.after(12_000,self.periodic_update_check)
        if all(self.core.config.get(k) for k in ('server_url','token','name')):
            self.root.after(400,self.connect_automatically)

    def text(self,parent,value='',size=10,bold=False,fg=TEXT,bg=None,**kwargs):
        return tk.Label(parent,text=value,font=('Segoe UI',size,'bold' if bold else 'normal'),
                        bg=bg or parent.cget('bg'),fg=fg,**kwargs)

    def surface(self,parent,**kwargs):
        return RoundedCard(parent,**kwargs)

    def action(self,parent,title,callback,primary=False,soft=False,**opts):
        return RoundedButton(parent,title,callback,primary=primary,soft=soft)

    def build(self):
        top=tk.Frame(self.root,bg=BG,padx=26,pady=20)
        top.pack(fill='x')
        logo=tk.Canvas(top,width=40,height=40,highlightthickness=0,bg=BG)
        logo.pack(side='left',padx=(0,12))
        logo.create_oval(4,4,36,36,outline=CYAN,width=3)
        logo.create_oval(13,13,27,27,outline=CYAN,width=2)
        logo.create_line(20,2,20,38,fill=CYAN,width=1)
        logo.create_line(2,20,38,20,fill=CYAN,width=1)
        brand=tk.Frame(top,bg=BG)
        brand.pack(side='left',anchor='w')
        self.text(brand,'SquadLoot',20,True).pack(anchor='w')
        self.text(brand,'ZERO BUILD  ·  SQUAD LIVE  ·  REPLAY VERIFIED',9,True,MUTED).pack(anchor='w')
        self.top_status=tk.StringVar(value='Nicht verbunden')
        tk.Label(top,textvariable=self.top_status,font=('Segoe UI',10,'bold'),bg=CARD2,
                 fg=MUTED,padx=15,pady=9).pack(side='right',padx=(12,0))
        self.text(top,'LIVE + REPLAY',9,True,CYAN).pack(side='right')

        body=tk.Frame(self.root,bg=BG,padx=18,pady=0)
        body.pack(fill='both',expand=True)
        sidebar=tk.Frame(body,bg=SIDE,width=188,padx=12,pady=15,
                         highlightbackground=LINE,highlightthickness=1)
        sidebar.pack(side='left',fill='y',padx=(0,14),pady=(0,8))
        sidebar.pack_propagate(False)
        self.text(sidebar,'NAVIGATION',9,True,MUTED).pack(anchor='w',padx=7,pady=(5,14))
        navitems=[('live','◉  Dashboard'),('settings','⚙  Verbindung'),('vision','◈  Live-Erkennung'),('updates','↻  Updates')]
        for key,title in navitems:
            b=tk.Button(sidebar,text=title,command=lambda k=key:self.show_page(k),
                        font=('Segoe UI',11,'bold'),anchor='w',bg=SIDE,fg=TEXT,
                        relief='flat',bd=0,highlightthickness=0,padx=12,pady=14,cursor='hand2',
                        activebackground=BUTTON,activeforeground=TEXT)
            b.pack(fill='x',pady=3)
            self.nav[key]=b
        tk.Frame(sidebar,bg=SIDE).pack(fill='both',expand=True)
        self.text(sidebar,'APP VERSION',9,True,MUTED).pack(anchor='w',padx=7)
        self.text(sidebar,'v'+current_version(),13,True,CYAN).pack(anchor='w',padx=7,pady=(0,12))
        self.text(sidebar,'Privat  |  Keine Game-Mods',9,fg=MUTED).pack(anchor='w',padx=7)
        self.text(sidebar,'Daten: dein Pi',9,fg=MUTED).pack(anchor='w',padx=7,pady=(2,10))

        self.content=tk.Frame(body,bg=BG)
        self.content.pack(side='left',fill='both',expand=True,pady=(0,8))
        for key in ('live','settings','vision','updates'):
            self.views[key]=tk.Frame(self.content,bg=BG)
        self.build_live()
        self.build_settings()
        self.build_vision()
        self.build_updates()

        footer=tk.Frame(self.root,bg=BG,padx=24,pady=10)
        footer.pack(fill='x')
        self.status_var=tk.StringVar(value='Bereit. Verbinde dich unter Verbindung.')
        self.status_label=self.text(footer,'',10,fg=MUTED,textvariable=self.status_var,anchor='w')
        self.status_label.pack(side='left',fill='x',expand=True)
        self.text(footer,'Lokal analysiert. Synchronisiert nur Zaehlwerte.',9,fg=MUTED).pack(side='right')
        footer.pack_forget()
        body.pack_forget()
        footer.pack(side='bottom',fill='x')
        body.pack(fill='both',expand=True)

    def show_page(self,key):
        if self.active==key:return
        if self.active:self.views[self.active].pack_forget()
        self.views[key].pack(fill='both',expand=True)
        self.active=key
        for k,b in self.nav.items():
            b.configure(bg=BUTTON if k==key else SIDE,fg=CYAN if k==key else TEXT)

    def page_title(self,parent,title,subtitle):
        self.text(parent,title,20,True).pack(anchor='w',pady=(0,4))
        self.text(parent,subtitle,10,fg=MUTED,wraplength=770,justify='left').pack(anchor='w',pady=(0,16))

    def make_kpi(self,parent,label,color=CYAN):
        box=self.surface(parent)
        top=tk.Frame(box.body,bg=CARD,padx=12,pady=7)
        top.pack(fill='both',expand=True)
        self.text(top,label.upper(),9,True,MUTED).pack(anchor='w')
        val=tk.StringVar(value='0')
        self.text(top,'',25,True,color,textvariable=val).pack(anchor='w',pady=(4,0))
        return box,val

    def build_live(self):
        page=self.views['live']
        self.page_title(page,'Dein Squad. Dein Loot.','Kisten während der Runde im Blick  ·  Replay-Daten bestätigen das Ergebnis nach dem Match.')
        cards=tk.Frame(page,bg=BG)
        cards.pack(fill='x',pady=(0,13))
        self.kpi={}
        for i,(key,label,color) in enumerate([
            ('round','🧭  AKTUELLE RUNDE',CYAN),('squad','📦  SQUAD-KISTEN',GREEN),
            ('mine','⚡  LIVE-ZÄHLER (BETA)',AMBER),('verified','✓  REPLAY-MATCHES',CYAN)]):
            box,var=self.make_kpi(cards,label,color)
            box.grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 5,0))
            cards.grid_columnconfigure(i,weight=1)
            self.kpi[key]=var
        middle=tk.Frame(page,bg=BG)
        middle.pack(fill='both',expand=True,pady=(0,13))
        middle.columnconfigure(0,weight=1)
        middle.columnconfigure(1,weight=1)
        middle.rowconfigure(0,weight=1)
        control=self.surface(middle)
        control.grid(row=0,column=0,sticky='nsew',padx=(0,7))
        pad=tk.Frame(control.body,bg=CARD,padx=9,pady=7)
        pad.pack(fill='both',expand=True)
        self.text(pad,'Dein Live-Tracker',15,True).pack(anchor='w')
        self.local_var=tk.StringVar(value='0 Kisten  |  0 zerstoert  |  0 Munition  |  0 Obst')
        self.text(pad,'',10,fg=MUTED,textvariable=self.local_var).pack(anchor='w',pady=(5,14))
        ctr=tk.Frame(pad,bg=CARD)
        ctr.pack(fill='x')
        buttons=[('+ Truhe',lambda:self.core.adjust('manual',1),True),
                 ('- Truhe',lambda:self.core.adjust('manual',-1),False),
                 ('+ Zerstoert',self.destroyed,False),
                 ('+ Munition',lambda:self.core.adjust('ammo',1),False),
                 ('+ Obstbox',lambda:self.core.adjust('food',1),False),
                 ('Reset',self.confirm_reset,False)]
        for i,(label,callback,primary) in enumerate(buttons):
            btn=self.action(ctr,label,callback,primary=primary)
            btn.grid(row=i//3,column=i%3,sticky='ew',padx=3,pady=4)
        for j in range(3):ctr.columnconfigure(j,weight=1)
        self.text(pad,'Aktionen',9,True,MUTED).pack(anchor='w',pady=(18,7))
        ops=tk.Frame(pad,bg=CARD)
        ops.pack(fill='x')
        self.action(ops,'Neue Squad-Runde',self.start_round,soft=True).pack(side='left',padx=(0,7))
        self.action(ops,'Replay auswerten',self.run_chestcounter,soft=True).pack(side='left')
        ops2=tk.Frame(pad,bg=CARD)
        ops2.pack(fill='x',pady=(7,0))
        self.action(ops2,'Live-HUD',self.toggle_overlay).pack(side='left',padx=(0,7))
        self.action(ops2,'Web-Dashboard',self.open_dashboard).pack(side='left')

        team=self.surface(middle)
        team.grid(row=0,column=1,sticky='nsew',padx=(7,0))
        inside=tk.Frame(team.body,bg=CARD,padx=9,pady=7)
        inside.pack(fill='both',expand=True)
        bar=tk.Frame(inside,bg=CARD)
        bar.pack(fill='x')
        self.text(bar,'Squad in dieser Runde',15,True).pack(side='left')
        self.team_hint=tk.StringVar(value='Keine Spieler erkannt')
        self.text(bar,'',9,True,GREEN,textvariable=self.team_hint).pack(side='right')
        self.members_box=tk.Frame(inside,bg=CARD)
        self.members_box.pack(fill='both',expand=True,pady=(13,0))

        history=self.surface(page)
        history.pack(fill='x')
        histinside=tk.Frame(history.body,bg=CARD,padx=9,pady=6)
        histinside.pack(fill='x')
        self.text(histinside,'Letzte Runden',13,True).pack(anchor='w',pady=(0,6))
        self.history_box=tk.Frame(histinside,bg=CARD)
        self.history_box.pack(fill='x')

    def build_settings(self):
        page=self.views['settings']
        self.page_title(page,'Verbindung & Accounts','Deine Zugangsdaten bleiben lokal. Der Server bekommt keine Screenshots oder Replay-Dateien.')
        holder=self.surface(page)
        holder.pack(fill='both',expand=True)
        form=tk.Frame(holder.body,bg=CARD,padx=12,pady=10)
        form.pack(fill='both',expand=True)
        rows=[('server_url','Server-URL (HTTPS)'),('token','Squad-Token'),
              ('cf_access_client_id','Cloudflare Access Client-ID'),
              ('cf_access_client_secret','Cloudflare Access Secret'),
              ('name','Dein Live-Anzeigename'),('data_json','ChestCounter data.json'),
              ('replay_dir','Fortnite Replay-Ordner'),('chestcounter_exe','Pfad zur ChestCounter.exe')]
        self.secret_entries=[]
        for i,(key,title) in enumerate(rows):
            self.text(form,title,10,fg=MUTED).grid(row=i,column=0,sticky='w',padx=(0,17),pady=8)
            var=tk.StringVar(value=self.core.config.get(key,''))
            secret=key in ('token','cf_access_client_secret')
            entry=tk.Entry(form,textvariable=var,show='*' if secret else '',
                           bg='#091829',fg=TEXT,insertbackground=TEXT,relief='flat',bd=0,
                           highlightthickness=1,highlightbackground=LINE,highlightcolor=CYAN,
                           font=('Segoe UI',10))
            entry.grid(row=i,column=1,sticky='ew',pady=7,ipady=7)
            if secret:self.secret_entries.append(entry)
            self.config_fields[key]=var
        form.columnconfigure(1,weight=1)
        buttons=tk.Frame(form,bg=CARD)
        buttons.grid(row=len(rows),column=1,sticky='w',pady=(15,4))
        self.action(buttons,'Speichern & verbinden',self.connect,True).pack(side='left',padx=(0,9))
        self.action(buttons,'Alle Replays synchronisieren',self.sync_all).pack(side='left')
        self.show_secrets_var=tk.BooleanVar(value=False)
        check=tk.Checkbutton(form,text='Geheimnisse anzeigen',variable=self.show_secrets_var,
                             command=self.toggle_secrets,bg=CARD,fg=MUTED,
                             activebackground=CARD,activeforeground=TEXT,selectcolor=SIDE,
                             font=('Segoe UI',9))
        check.grid(row=len(rows)+1,column=1,sticky='w',pady=(7,2))
        self.text(form,'Bei Cloudflare Access werden Client-ID und Secret benoetigt. Beim Accountwechsel den Live-Namen anpassen.',
                  9,fg=MUTED,wraplength=615,justify='left').grid(row=len(rows)+2,column=0,columnspan=2,sticky='w',pady=(14,0))

    def build_vision(self):
        page=self.views['vision']
        self.page_title(page,'Live-Erkennung (Beta)','Opt-in: Nur Bildschirmbereich + Interaktionstaste. Keine Fortnite-Modifikation.')
        panel=self.surface(page)
        panel.pack(fill='x')
        inside=tk.Frame(panel.body,bg=CARD,padx=12,pady=12)
        inside.pack(fill='x')
        self.text(inside,'BETA / NICHT VERIFIZIERT',10,True,AMBER).pack(anchor='w',pady=(0,10))
        self.text(inside,'Ein Kistenversuch wird nur geschätzt, wenn der Suchhinweis sichtbar war,\n'
                         'du die konfigurierte Interaktionstaste gedrückt hast und der Hinweis verschwindet.\n'
                         'Das ist kein sicherer Nachweis für eine geöffnete Truhe.',
                  11,fg=TEXT,justify='left').pack(anchor='w',pady=(0,20))
        row=tk.Frame(inside,bg=CARD)
        row.pack(anchor='w')
        self.action(row,'PNG-Vorlage auswaehlen',self.select_vision_template,primary=True).pack(side='left',padx=(0,9))
        self.action(row,'Erkennung starten / stoppen',self.toggle_vision).pack(side='left')
        keyrow=tk.Frame(inside,bg=CARD)
        keyrow.pack(anchor='w',pady=(14,0))
        self.text(keyrow,'Interaktionstaste',10,fg=MUTED).pack(side='left',padx=(0,13))
        self.vision_key=tk.StringVar(value=self.core.config.get('interact_key','E'))
        tk.Entry(keyrow,textvariable=self.vision_key,width=4,font=('Segoe UI',12,'bold'),
                 bg='#091829',fg=TEXT,insertbackground=TEXT,relief='flat',
                 highlightbackground=LINE,highlightthickness=1).pack(side='left')
        self.text(keyrow,'1 Taste (A–Z oder 0–9), Standard E',9,fg=MUTED).pack(side='left',padx=(12,0))
        self.text(inside,'Performance-Modus: nur zentraler Bildschirmausschnitt, max. 2,5 Bilder/Sekunde,\n'
                         'nur bei aktivem Fortnite-Fenster. Keine Bilder oder Tastendrücke werden übertragen.',
                  9,fg=MUTED,justify='left').pack(anchor='w',pady=(12,0))
        self.vision_var=tk.StringVar(value='Bildschirmmodus ist AUS')
        self.text(inside,'',10,True,CYAN,textvariable=self.vision_var,wraplength=710,justify='left').pack(anchor='w',pady=(18,5))
        self.text(inside,'Optional: SETUP_VISION.cmd ausfuehren, dann den Durchsuchen-Hinweis als kleinen PNG-Ausschnitt speichern.\n'
                         'Der Screenshot bleibt auf deinem PC.',9,fg=MUTED,justify='left').pack(anchor='w',pady=(0,5))

    def build_updates(self):
        page=self.views['updates']
        self.page_title(page,'Automatische Updates','Einmal installieren. Danach kommen neue Versionen geschuetzt von deinem Raspberry Pi.')
        panel=self.surface(page)
        panel.pack(fill='x')
        inside=tk.Frame(panel.body,bg=CARD,padx=12,pady=12)
        inside.pack(fill='x')
        self.text(inside,'INSTALLIERTE VERSION',9,True,MUTED).pack(anchor='w')
        self.text(inside,'SquadLoot v'+current_version(),21,True,CYAN).pack(anchor='w',pady=(4,12))
        self.update_status=tk.StringVar(value='Keine Updates heruntergeladen. Automatische Pruefung laeuft im Hintergrund.')
        self.text(inside,'',10,fg=TEXT,textvariable=self.update_status,wraplength=700,justify='left').pack(anchor='w',pady=(0,16))
        self.autoupdate_var=tk.BooleanVar(value=self.core.config.get('auto_update',True))
        tk.Checkbutton(inside,text='Updates beim Start und waehrend des Betriebs automatisch pruefen',
                       variable=self.autoupdate_var,command=self.toggle_autoupdate,
                       font=('Segoe UI',10),bg=CARD,fg=TEXT,selectcolor=SIDE,
                       activebackground=CARD,activeforeground=TEXT).pack(anchor='w',pady=(0,20))
        row=tk.Frame(inside,bg=CARD)
        row.pack(anchor='w')
        self.action(row,'Jetzt pruefen',self.check_updates,primary=True).pack(side='left',padx=(0,9))
        self.install_btn=self.action(row,'Neu starten & installieren',self.restart_and_install)
        self.install_btn.pack(side='left')
        self.install_btn.configure(state='disabled')
        self.text(inside,'Updates werden nur ueber deine konfigurierte HTTPS-/Cloudflare-Verbindung geladen,\n'
                         'per SHA-256 geprueft und beim naechsten Start installiert.\n'
                         'Es wird niemals mitten im Match neu gestartet.',9,fg=MUTED,justify='left').pack(anchor='w',pady=(25,0))
        self.release_notes=tk.StringVar(value='Release-Notizen erscheinen hier, sobald eine neue Version bereitliegt.')
        self.text(inside,'',10,fg=GREEN,textvariable=self.release_notes,wraplength=700,justify='left').pack(anchor='w',pady=(15,0))

    def toggle_autoupdate(self):
        enabled=self.autoupdate_var.get()
        self.core.set_config({'auto_update':enabled})
        self.update_status.set('Automatische Updates aktiviert.' if enabled else 'Automatische Updates deaktiviert.')
        if enabled:self.check_updates()

    def periodic_update_check(self):
        self.check_updates()
        self.root.after(20*60*1000,self.periodic_update_check)

    def check_updates(self):
        if self.update_busy or not self.core.config.get('auto_update',True):return
        if not (self.core.config.get('server_url') and self.core.config.get('token')):return
        self.update_busy=True
        self.update_status.set('Pruefe auf neue Versionen ...')
        def job():
            try:
                ver=check_and_stage(self.core.config)
                self.events.put(('update',ver or ''))
            except Exception as exc:
                log_error(exc)
                self.events.put(('update_error',str(exc)[:150]))
        threading.Thread(target=job,daemon=True,name='SquadLootUpdateCheck').start()

    def restart_and_install(self):
        if not self.update_pending:return
        if messagebox.askyesno('Update installieren','SquadLoot wird geschlossen und mit der neuen Version wieder gestartet. Jetzt installieren?'):
            subprocess.Popen([sys.executable,str(Path(__file__).resolve().parent/'bootstrap.py')],
                             cwd=str(Path(__file__).resolve().parent))
            self.close()

    def toggle_secrets(self):
        for entry in self.secret_entries:entry.configure(show='' if self.show_secrets_var.get() else '*')

    def connect_automatically(self):
        try:self.core.start()
        except Exception as exc:self.status_var.set(str(exc))

    def connect(self):
        changes={key:var.get().strip() for key,var in self.config_fields.items()}
        if not changes.get('name'):
            messagebox.showerror('Anzeigename fehlt','Bitte deinen Live-Spielernamen eintragen.');return
        try:
            from client_core import Api
            Api(changes['server_url'],changes['token'],changes['cf_access_client_id'],changes['cf_access_client_secret'])
            self.core.set_config(changes)
            self.core.start()
            self.status_var.set('Verbinde mit SquadLoot auf deinem Pi ...')
            self.show_page('live')
            self.check_updates()
        except Exception as exc:
            messagebox.showerror('Verbindung',str(exc))

    def confirm_reset(self):
        if messagebox.askyesno('Zaehler zuruecksetzen','Nur deine vorlaeufigen lokalen Zaehler zuruecksetzen?'):
            self.core.reset_local_counters()

    def destroyed(self):
        self.core.adjust('manual',1)
        self.core.adjust('destroyed',1)

    def job(self,func):
        def runner():
            try:self.events.put(('info',str(func())))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=runner,daemon=True).start()

    def sync_all(self):
        self.job(lambda: str(self.core.sync_matches(self.core.credentials(),max_items=100000))+' Matches synchronisiert')

    def start_round(self):
        if messagebox.askyesno('Neue Runde','Eine neue Squad-Runde fuer alle verbundenen Spieler starten?'):
            self.job(lambda:'Neue Squad-Runde #'+str(self.core.new_round()))

    def run_chestcounter(self):
        exe=chestcounter_exe(self.core.config)
        if not exe:
            messagebox.showwarning('ChestCounter fehlt','Bitte in Verbindung den Pfad zur ChestCounter.exe eintragen.');return
        self.status_var.set('ChestCounter wertet vorhandene Replays aus ...')
        def run():
            result=subprocess.run([str(exe),'--once'],capture_output=True,text=True,timeout=200,errors='replace')
            if result.returncode:raise RuntimeError('ChestCounter Exit '+str(result.returncode)+': '+result.stderr[-200:])
            n=self.core.sync_matches(self.core.credentials(),max_items=100000)
            return f'{n} Matches nach Replay-Auswertung synchronisiert'
        self.job(run)

    def open_dashboard(self):
        url=self.core.config.get('server_url','')
        if url:webbrowser.open(url)
        else:messagebox.showwarning('Server fehlt','Zuerst eine Server-URL eintragen.')

    def select_vision_template(self):
        name=filedialog.askopenfilename(title='PNG der Suchaufforderung',filetypes=[('PNG','*.png'),('Bilder','*.png *.jpg *.jpeg')])
        if name:
            self.core.set_config({'vision_template':name})
            self.vision_var.set('Vorlage: '+Path(name).name+' / Erkennung noch AUS')

    def toggle_vision(self):
        if self.vision and self.vision.thread and self.vision.thread.is_alive():
            self.vision.stop_now();self.vision_var.set('Bildschirmmodus AUS');return
        try:
            key=self.vision_key.get().strip().upper()
            if len(key)!=1 or not key.isascii() or not key.isalnum():
                raise ValueError('Bitte genau eine Interaktionstaste A–Z oder 0–9 eintragen.')
            self.core.set_config({'interact_key':key})
            self.vision=VisionDetector(self.core,self.core.config.get('vision_template',''),key=key)
            self.vision.start();self.vision_var.set('AKTIV - vorläufige Zählung; Replay bestätigt später')
        except Exception as exc:messagebox.showwarning('Bildschirm-Erkennung',str(exc))

    def toggle_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy();self.overlay=None;return
        self.overlay=tk.Toplevel(self.root)
        self.overlay.title('SquadLoot HUD - geschaetzt')
        self.overlay.geometry('390x230+40+120')
        self.overlay.configure(bg=BG)
        self.overlay.attributes('-topmost',True)
        self.overlay.protocol('WM_DELETE_WINDOW',self.toggle_overlay)
        self.overlay_var=tk.StringVar(value='Keine aktuelle Runde')
        tk.Label(self.overlay,textvariable=self.overlay_var,bg=SIDE,fg=TEXT,
                 font=('Consolas',12),justify='left',anchor='nw',padx=12,pady=12).pack(fill='both',expand=True)
        buttons=tk.Frame(self.overlay,bg=SIDE)
        buttons.pack(fill='x',padx=10,pady=8)
        self.action(buttons,'+ Truhe',lambda:self.core.adjust('manual',1),True).pack(side='left',padx=(0,6))
        self.action(buttons,'- Truhe',lambda:self.core.adjust('manual',-1)).pack(side='left',padx=(0,6))
        self.action(buttons,'Schliessen',self.toggle_overlay).pack(side='left')

    def render_members(self,members):
        snapshot=json.dumps(members,ensure_ascii=False,sort_keys=True)
        if snapshot==self.last_team:return
        self.last_team=snapshot
        for widget in self.members_box.winfo_children():widget.destroy()
        if not members:
            self.text(self.members_box,'Noch keine Spieler fuer diese Runde erkannt.',10,fg=MUTED).pack(anchor='w',pady=12)
            return
        for index,member in enumerate(members[:8]):
            row=tk.Frame(self.members_box,bg=CARD2,padx=12,pady=9)
            row.pack(fill='x',pady=4)
            led=tk.Canvas(row,width=12,height=18,bg=CARD2,highlightthickness=0)
            led.create_oval(2,5,10,13,fill=GREEN if member.get('online') else MUTED,outline='')
            led.pack(side='left',padx=(0,8))
            label=tk.Frame(row,bg=CARD2)
            label.pack(side='left',fill='x',expand=True)
            self.text(label,str(member.get('name','Spieler'))[:32],11,True,bg=CARD2).pack(anchor='w')
            actual=member.get('verified_chests')
            self.text(label,'Replay bestaetigt' if actual is not None else 'Live-Schaetzung',9,
                      fg=GREEN if actual is not None else MUTED,bg=CARD2).pack(anchor='w')
            num=actual if actual is not None else member.get('live_chests',0)
            self.text(row,str(num),20,True,GREEN if actual is not None else CYAN,bg=CARD2).pack(side='right')

    def render_history(self,history):
        snapshot=json.dumps(history[:3],ensure_ascii=False,sort_keys=True)
        if snapshot==self.last_history:return
        self.last_history=snapshot
        for child in self.history_box.winfo_children():child.destroy()
        if not history:
            self.text(self.history_box,'Noch keine ausgewerteten Matches vorhanden.',10,fg=MUTED).pack(anchor='w',pady=5)
            return
        for rowdata in history[:3]:
            row=tk.Frame(self.history_box,bg=CARD)
            row.pack(fill='x',pady=3)
            left=str(rowdata.get('breakdown',''))[:85] or 'Match'
            self.text(row,left,10,bg=CARD,anchor='w').pack(side='left',fill='x',expand=True)
            self.text(row,str(rowdata.get('chests',0))+' Kisten',10,True,CYAN,bg=CARD).pack(side='right')

    def refresh(self):
        events=[]
        while not self.events.empty():events.append(self.events.get_nowait())
        with self.core.lock:
            manual=self.core.manual;vision=self.core.vision
            ammo=self.core.ammo;food=self.core.food;destroyed=self.core.destroyed
            rid=self.core.round_id;status=self.core.status
            connected=self.core.connected
            data=dict(self.core.current_state)
        rd=data.get('round') or {}
        members=rd.get('members') or []
        self.kpi['round'].set('#'+str(rd.get('id') or rid or '-'))
        self.kpi['squad'].set(str(rd.get('chests_total',0)))
        self.kpi['mine'].set(str(max(manual,vision)))
        self.kpi['verified'].set(str(data.get('total_matches',0)))
        self.local_var.set(f'{manual} manuell  /  {vision} Bildschirm?  |  {destroyed} zerstoert  |  {ammo} Munition  |  {food} Obst')
        self.team_hint.set(str(len(members))+' Spieler' if members else 'Warte auf Spieler')
        self.render_members(members)
        self.render_history(data.get('history') or [])
        self.top_status.set('Verbunden / Pi online' if connected else 'Offline / pruefen')
        self.status_label.configure(fg=GREEN if connected else (RED if status.startswith('Fehler') else MUTED))
        self.status_var.set(status)
        if self.overlay is not None:
            self.overlay_var.set('Squad '+str(rd.get('chests_total',0))+' Kisten\n'
                                 'Dein Zaehler '+str(max(manual,vision))+'\n\n'
                                 '\n'.join(f"{m.get('name','Spieler')[:14]}: {m.get('verified_chests') if m.get('verified_chests') is not None else m.get('live_chests',0)}" for m in members[:4]))
        if self.vision and self.vision.error:
            self.vision_var.set('Fehler: '+self.vision.error)
        elif self.vision and self.vision.thread and self.vision.thread.is_alive():
            self.vision_var.set(f'{self.vision.state}  ·  {self.vision.count} vorläufige Kisten  ·  {self.vision.perf_ms:.0f} ms/Bild')
        for kind,msg in events:
            if kind=='error':
                self.status_var.set('Fehler: '+msg[:250]);self.status_label.configure(fg=RED)
            elif kind=='info':self.status_var.set(msg)
            elif kind=='update':
                self.update_busy=False
                if msg:
                    self.update_pending=True
                    self.install_btn.configure(state='normal')
                    self.update_status.set('Version '+msg+' heruntergeladen. Wird beim naechsten Start installiert.')
                    self.release_notes.set('Du kannst normal weiterspielen. Der Client startet nicht automatisch neu.')
                else:self.update_status.set('Aktuell. Keine neue Version verfuegbar.')
            elif kind=='update_error':
                self.update_busy=False
                self.update_status.set('Update-Check fehlgeschlagen, aktuelle Version laeuft weiter: '+msg)
        self.root.after(1000,self.refresh)

    def close(self):
        if self.vision:self.vision.stop_now()
        self.core.shutdown()
        try:self.root.destroy()
        except tk.TclError:pass

    def run(self):self.root.mainloop()


def main():
    p=argparse.ArgumentParser(description='SquadLoot Desktop')
    p.add_argument('--once',action='store_true')
    args=p.parse_args()
    if args.once:
        conf=read_json(CONFIG,{})
        if not conf.get('server_url') or not conf.get('token'):
            raise SystemExit('Zuerst STARTEN.cmd verwenden und verbinden.')
        exe=chestcounter_exe(conf)
        if exe:
            result=subprocess.run([str(exe),'--once'],timeout=200)
            if result.returncode:raise SystemExit('ChestCounter Exit '+str(result.returncode))
        count,state=sync_once(conf)
        print('Fertig:',count,'Replay-Datensaetze; Runde:',(state.get('round') or {}).get('id','-'))
    else:Gui().run()


if __name__=='__main__':main()
