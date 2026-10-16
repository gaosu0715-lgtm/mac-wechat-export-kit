# SPDX-License-Identifier: MIT
# Copyright (c) 2026 mac-wechat-export-kit contributors
# Reused from reviewed private permission_windows.py; see docs/SOURCES.md.
"""Verify system permission windows without inspecting any WeChat UI content.

Only current GUI-session CG metadata and AX roles/geometry/button labels in
allowlisted system agents are read. No screenshots, static text, text fields,
window titles, chat windows, clicks or permission-request APIs.
"""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import time

AGENTS={'SecurityAgent','CoreServicesUIAgent','UserNotificationCenter'}
ALLOW={'allow','always allow','允许','始终允许','允许一次'}
DENY={'deny',"don't allow",'don’t allow','不允许','拒绝'}


class AXQueryError(Exception):
    def __init__(self,code):self.code=code


QUERY_ERRORS=(AXQueryError,OSError,RuntimeError,ValueError,TypeError,subprocess.TimeoutExpired)


def button_features(labels):
    normalized={s.strip().lower() for s in labels if isinstance(s,str)}
    return {'allow_choice':bool(normalized&ALLOW),'deny_choice':bool(normalized&DENY)}


def evaluate(snapshot):
    """Pure tri-state decision. Count alone can never confirm a permission UI."""
    result={'status':'no_verified_permission_window','scope':'allowlisted_system_agents_current_gui_session',
            'verified':[], 'unverified':[],
            'hidden_agent_windows':0,'agent_count':0}
    if snapshot.get('session_verified') is not True:
        result['status']='unknown';result['unverified']=[{'reason':'current_gui_session_unverified'}]
        return result
    if snapshot.get('inventory_ok') is not True or snapshot.get('screen_query_ok') is not True:
        result['status']='unknown';result['unverified']=[{'reason':'window_or_process_query_failed'}]
        return result
    for agent in snapshot.get('agents',[]):
        result['agent_count']+=1
        base={'agent':agent['agent'],'pid':agent['pid']}
        if not agent.get('identity_verified'):
            result['unverified'].append(dict(base,reason='system_agent_identity_unverified'));continue
        if agent.get('query_error'):
            result['unverified'].append(dict(base,reason='agent_ax_query_failed'));continue
        windows=agent.get('windows',[])
        if not windows and agent.get('visible_count',0):
            result['unverified'].append(dict(base,reason='visible_agent_window_not_exposed'));continue
        for window in windows:
            if window.get('visible') is False:
                result['hidden_agent_windows']+=1;continue
            if (window.get('visible') is not True or window.get('owner_verified') is not True or
                    window.get('current_session') is not True):
                result['unverified'].append(dict(base,reason='window_owner_visibility_or_session_unverified'));continue
            features=window.get('features',{})
            if features.get('allow_choice') is True and features.get('deny_choice') is True:
                result['verified'].append(dict(base,window_id=window['window_id'],
                    visible=True,current_session=True,permission_choices_verified=True))
            else:
                reason='minimal_feature_query_failed' if window.get('feature_query_error') else 'visible_agent_window_type_unverified'
                result['unverified'].append(dict(base,window_id=window['window_id'],reason=reason))
    if result['verified']:result['status']='verified_permission_request'
    elif result['unverified']:result['status']='unknown'
    return result


class PermissionObserver:
    def __init__(self,backend,report=lambda value:None):
        self.backend=backend;self.report=report;self.last_observation=None;self.last_serialized=None

    def check(self):
        try:snapshot=self.backend.snapshot()
        except TimeoutError:raise # Preserve an outer observation deadline.
        except QUERY_ERRORS:
            snapshot={'session_verified':True,'inventory_ok':False,'screen_query_ok':False}
        result=evaluate(snapshot);self.last_observation=result
        serialized=json.dumps(result,sort_keys=True)
        if serialized!=self.last_serialized:
            self.report(result);self.last_serialized=serialized
        if result['status']=='verified_permission_request':raise RuntimeError('system_permission_window_present')
        if result['status']=='unknown':raise RuntimeError('permission_window_unverified')
        return result


class Point(C.Structure):
    _fields_=[('x',C.c_double),('y',C.c_double)]


class Size(C.Structure):
    _fields_=[('width',C.c_double),('height',C.c_double)]


class MacPermissionBackend:
    def __init__(self,command):
        self.command=command
        self.cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.ax=C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        self.cg=C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        for name,args,result in (
            ('CFRelease',[C.c_void_p],None),('CFGetTypeID',[C.c_void_p],C.c_ulong),
            ('CFArrayGetCount',[C.c_void_p],C.c_long),('CFArrayGetValueAtIndex',[C.c_void_p,C.c_long],C.c_void_p),
            ('CFDictionaryGetValue',[C.c_void_p,C.c_void_p],C.c_void_p),
            ('CFStringCreateWithCString',[C.c_void_p,C.c_char_p,C.c_uint32],C.c_void_p),
            ('CFStringGetCString',[C.c_void_p,C.c_void_p,C.c_long,C.c_uint32],C.c_bool),
            ('CFNumberGetValue',[C.c_void_p,C.c_int,C.c_void_p],C.c_bool),
            ('CFBooleanGetValue',[C.c_void_p],C.c_bool)):
            fn=getattr(self.cf,name);fn.argtypes=args;fn.restype=result
        for name in ('CFStringGetTypeID','CFNumberGetTypeID','CFBooleanGetTypeID','CFArrayGetTypeID','CFDictionaryGetTypeID'):
            getattr(self.cf,name).restype=C.c_ulong
        for name,args,result in (
            ('AXIsProcessTrusted',[],C.c_bool),
            ('AXUIElementCreateApplication',[C.c_int],C.c_void_p),
            ('AXUIElementGetPid',[C.c_void_p,C.POINTER(C.c_int)],C.c_int),
            ('AXUIElementSetMessagingTimeout',[C.c_void_p,C.c_float],C.c_int),
            ('AXUIElementCopyAttributeValue',[C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)],C.c_int),
            ('AXValueGetValue',[C.c_void_p,C.c_int,C.c_void_p],C.c_bool)):
            fn=getattr(self.ax,name);fn.argtypes=args;fn.restype=result
        self.cg.CGSessionCopyCurrentDictionary.argtypes=[];self.cg.CGSessionCopyCurrentDictionary.restype=C.c_void_p
        self.cg.CGWindowListCopyWindowInfo.argtypes=[C.c_uint32,C.c_uint32];self.cg.CGWindowListCopyWindowInfo.restype=C.c_void_p
        if not self.ax.AXIsProcessTrusted():raise RuntimeError('prompt_observer_not_already_trusted')

    def key(self,name):return self.cf.CFStringCreateWithCString(None,name.encode(),0x08000100)


    def query_guard(self):
        deadline=getattr(self,'query_deadline',None)
        if deadline is not None and time.monotonic()>=deadline:raise AXQueryError(-1)

    def dict_value(self,obj,name):
        key=self.key(name)
        try:return self.cf.CFDictionaryGetValue(obj,key)
        finally:self.cf.CFRelease(key)

    def scalar(self,value):
        if not value:return None
        kind=self.cf.CFGetTypeID(value)
        if kind==self.cf.CFBooleanGetTypeID():return bool(self.cf.CFBooleanGetValue(value))
        if kind==self.cf.CFNumberGetTypeID():
            number=C.c_double()
            return number.value if self.cf.CFNumberGetValue(value,13,C.byref(number)) else None
        if kind==self.cf.CFStringGetTypeID():
            buffer=C.create_string_buffer(512)
            if self.cf.CFStringGetCString(value,buffer,len(buffer),0x08000100):return buffer.value.decode('utf8','replace')
        return None

    def attribute(self,element,name):
        self.query_guard()
        key=self.key(name);value=C.c_void_p()
        try:error=self.ax.AXUIElementCopyAttributeValue(element,key,C.byref(value))
        finally:self.cf.CFRelease(key)
        if error:
            if value.value:self.cf.CFRelease(value)
            raise AXQueryError(error)
        if not value.value:raise RuntimeError('ax_attribute_empty')
        return value.value

    def scalar_attribute(self,element,name):
        value=self.attribute(element,name)
        try:return self.scalar(value)
        finally:self.cf.CFRelease(value)

    def geometry(self,window):
        point=Point();size=Size()
        for name,kind,out in [('AXPosition',1,point),('AXSize',2,size)]:
            value=self.attribute(window,name)
            try:
                if not self.ax.AXValueGetValue(value,kind,C.byref(out)):raise RuntimeError('ax_geometry_unavailable')
            finally:self.cf.CFRelease(value)
        return (point.x,point.y,size.width,size.height)

    def session_and_windows(self):
        session=self.cg.CGSessionCopyCurrentDictionary()
        if not session:return False,None
        try:
            # CGSession.h macro names differ from their CFSTR dictionary keys.
            verified=(self.scalar(self.dict_value(session,'kCGSSessionUserIDKey'))==os.geteuid() and
                      self.scalar(self.dict_value(session,'kCGSSessionOnConsoleKey')) is True and
                      self.scalar(self.dict_value(session,'kCGSessionLoginDoneKey')) is True)
        finally:self.cf.CFRelease(session)
        if not verified:return False,None
        array=self.cg.CGWindowListCopyWindowInfo(17,0) # Current on-screen WindowServer list, no desktop.
        if not array:return True,None
        windows=[]
        try:
            for i in range(self.cf.CFArrayGetCount(array)):
                row=self.cf.CFArrayGetValueAtIndex(array,i)
                pid=self.scalar(self.dict_value(row,'kCGWindowOwnerPID'))
                number=self.scalar(self.dict_value(row,'kCGWindowNumber'))
                visible=self.scalar(self.dict_value(row,'kCGWindowIsOnscreen'))
                alpha=self.scalar(self.dict_value(row,'kCGWindowAlpha'))
                bounds=self.dict_value(row,'kCGWindowBounds')
                if pid is None or number is None or visible is None or alpha is None or not bounds:return True,None
                if visible is not True or alpha<=0:continue
                rect=tuple(self.scalar(self.dict_value(bounds,key)) for key in ('X','Y','Width','Height'))
                if None in rect:return True,None
                if rect[2]>0 and rect[3]>0:windows.append({'pid':int(pid),'id':int(number),'bounds':rect})
            return True,windows
        finally:self.cf.CFRelease(array)

    def minimal_features(self,window):
        """Bounded traversal reads roles and button titles only, never text bodies."""
        labels=[];visited=[0]
        def visit(element,depth):
            visited[0]+=1
            if visited[0]>64 or depth>6:raise RuntimeError('ax_feature_limit')
            role=self.scalar_attribute(element,'AXRole')
            if role=='AXButton':
                labels.append(self.scalar_attribute(element,'AXTitle'))
                return
            # Static text, text inputs, web views and notification content are not traversed.
            if role not in ('AXWindow','AXGroup','AXScrollArea','AXSheet','AXSplitGroup'):return
            children=self.attribute(element,'AXChildren')
            try:
                if self.cf.CFGetTypeID(children)!=self.cf.CFArrayGetTypeID():raise RuntimeError('ax_children_type')
                count=self.cf.CFArrayGetCount(children)
                if count>32:raise RuntimeError('ax_feature_limit')
                for i in range(count):visit(self.cf.CFArrayGetValueAtIndex(children,i),depth+1)
            finally:self.cf.CFRelease(children)
        visit(window,0)
        return button_features(labels) # Raw labels are not retained or emitted.

    def agent_windows(self,pid,visible):
        app=self.ax.AXUIElementCreateApplication(pid);array=None
        try:
            self.ax.AXUIElementSetMessagingTimeout(app,0.25)
            try:array=self.attribute(app,'AXWindows')
            except AXQueryError as error:
                # Unsupported/no-value plus no on-screen window means no visible
                # candidate, not a failed transport or a hidden permission alert.
                if error.code in (-25205,-25212) and not visible:return []
                raise
            if self.cf.CFGetTypeID(array)!=self.cf.CFArrayGetTypeID():raise RuntimeError('ax_windows_type')
            count=self.cf.CFArrayGetCount(array)
            if count>16:raise RuntimeError('ax_window_limit')
            rows=[]
            for i in range(count):
                window=self.cf.CFArrayGetValueAtIndex(array,i)
                if not visible:
                    rows.append({'visible':False});continue
                try:
                    actual=C.c_int()
                    if self.ax.AXUIElementGetPid(window,C.byref(actual)) or actual.value!=pid:
                        rows.append({'visible':None,'owner_verified':False});continue
                    if self.scalar_attribute(window,'AXRole')!='AXWindow':
                        rows.append({'visible':None,'owner_verified':True});continue
                    if self.scalar_attribute(window,'AXMinimized') is True:
                        rows.append({'visible':False});continue
                    rect=self.geometry(window)
                    matches=[v for v in visible if all(abs(a-b)<=2 for a,b in zip(rect,v['bounds']))]
                    if not matches:
                        rows.append({'visible':None,'owner_verified':True});continue
                    if len(matches)!=1:
                        rows.append({'visible':None,'owner_verified':True});continue
                    row={'visible':True,'owner_verified':True,'current_session':True,'window_id':matches[0]['id']}
                    try:row['features']=self.minimal_features(window)
                    except TimeoutError:raise
                    except QUERY_ERRORS:row['feature_query_error']=True
                    rows.append(row)
                except TimeoutError:raise
                except QUERY_ERRORS:rows.append({'visible':None,'owner_verified':True})
            covered={row.get('window_id') for row in rows}
            if any(v['id'] not in covered for v in visible):
                rows.append({'visible':None,'owner_verified':True})
            return rows
        finally:
            if array:self.cf.CFRelease(array)
            if app:self.cf.CFRelease(app)

    def snapshot(self):
        self.query_deadline=time.monotonic()+3
        session,windows=self.session_and_windows()
        result={'session_verified':session,'screen_query_ok':windows is not None,'inventory_ok':False,'agents':[]}
        if not session or windows is None:return result
        self.query_guard()
        response=self.command(['/bin/ps','-axo','pid=,uid=,comm='],2)
        if response.returncode:return result
        result['inventory_ok']=True
        for line in response.stdout.splitlines():
            parts=line.strip().split(None,2)
            if len(parts)!=3 or not parts[0].isdigit() or not parts[1].isdigit():continue
            pid,uid=int(parts[0]),int(parts[1]);path=Path(parts[2]);name=path.name
            if name not in AGENTS:continue
            identity=str(path).startswith('/System/Library/') and uid in (0,os.geteuid())
            visible=[v for v in windows if v['pid']==pid]
            agent={'agent':name,'pid':pid,'identity_verified':identity,'visible_count':len(visible)}
            if identity:
                try:agent['windows']=self.agent_windows(pid,visible)
                except TimeoutError:raise
                except QUERY_ERRORS:agent['query_error']=True
            result['agents'].append(agent)
        return result
