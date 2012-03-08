from __future__ import with_statement
import os
import subprocess
import errno
import time
import sys
import threading

PIPE = subprocess.PIPE

if subprocess.mswindows:
	from win32file import ReadFile, WriteFile
	from win32pipe import PeekNamedPipe
	from _subprocess import TerminateProcess
	import win32event
	import msvcrt
else:
	from select import select
	import fcntl
	import signal

class ProcessList():
	def __init__(self):
		
		self.mutex = threading.RLock()
		self.processes = {}
		
	def put(self, proc):
		with self.mutex:
			self.processes[proc.pid] = proc
	
	def remove(self, pid):
		with self.mutex:
			if pid in self.processes:
				del self.processes[pid]
	
	def cleanupProcesses(self):
		with self.mutex:
			for pid in self.processes.keys():
				self.killPid(pid)

	if subprocess.mswindows:
		def killPid(self, pid):
			with self.mutex:
				TerminateProcess(pid)
				self.remove(pid)
	else:
		def killPid(self, pid):
			with self.mutex:
				try:
					os.kill(pid, signal.SIGKILL)
				except:
					pass #process is already dead
				self.remove(pid)

processList = ProcessList()

class Popen(subprocess.Popen):
	
	def __init__(self, args, bufsize=0, executable=None,
				stdin=None, stdout=None, stderr=None,
				preexec_fn=None, close_fds=False, shell=False,
				cwd=None, env=None, universal_newlines=False,
				startupinfo=None, creationflags=0):
		
		subprocess.Popen.__init__(self, args, bufsize, executable,
										stdin, stdout, stderr, preexec_fn, 
										close_fds, shell, cwd, env, 
										universal_newlines, startupinfo, 
										creationflags)
		processList.put(self)
	
	if subprocess.mswindows:
		def pollStdout(self, timeout):
			
			handle = msvcrt.get_osfhandle(self.stdout.fileno())
			result = win32event.WaitForSingleObject(handle,timeout)
			
			if result == win32event.WAIT_OBJECT_0:
				return True
			
			return False
	else:
		
		def pollStdout(self,timeout):
			
			if timeout < 0:
				timeout = None
			else:
				timeout = timeout / 1000.0
				
			ready, _, _ = select([self.stdout], [], [], timeout)
			if ready in [self.stdout]:
				return True
			
			return False
	
	def recv(self, maxsize=None):
		return self._recv('stdout', maxsize)
	
	def recv_err(self, maxsize=None):
		return self._recv('stderr', maxsize)

	def send_recv(self, input='', maxsize=None):
		return self.send(input), self.recv(maxsize), self.recv_err(maxsize)

	def get_conn_maxsize(self, which, maxsize):
		if maxsize is None:
			maxsize = 1024
		elif maxsize < 1:
			maxsize = 1
		return getattr(self, which), maxsize
	
	def _close(self, which):
		processList.remove(self.pid)
		getattr(self, which).close()
		setattr(self, which, None)
	
	if subprocess.mswindows:
		def send(self, input):
			if not self.stdin:
				return None

			try:
				x = msvcrt.get_osfhandle(self.stdin.fileno())
				(errCode, written) = WriteFile(x, input)
			except ValueError:
				return self._close('stdin')
			except (subprocess.pywintypes.error, Exception), why:
				if why[0] in (109, errno.ESHUTDOWN):
					return self._close('stdin')
				raise

			return written

		def _recv(self, which, maxsize):
			conn, maxsize = self.get_conn_maxsize(which, maxsize)
			if conn is None:
				return None
			
			try:
				x = msvcrt.get_osfhandle(conn.fileno())
				(read, nAvail, nMessage) = PeekNamedPipe(x, 0)
				if maxsize < nAvail:
					nAvail = maxsize
				if nAvail > 0:
					(errCode, read) = ReadFile(x, nAvail, None)
			except ValueError:
				return self._close(which)
			except (subprocess.pywintypes.error, Exception), why:
				if why[0] in (109, errno.ESHUTDOWN):
					return self._close(which)
				raise
			
			if self.universal_newlines:
				read = self._translate_newlines(read)
			return read

	else:
		def send(self, input):
			if not self.stdin:
				return None

			if not select([], [self.stdin], [], 0)[1]:
				return 0

			try:
				written = os.write(self.stdin.fileno(), input)
			except OSError, why:
				if why[0] == errno.EPIPE: #broken pipe
					return self._close('stdin')
				raise

			return written

		def _recv(self, which, maxsize):
			conn, maxsize = self.get_conn_maxsize(which, maxsize)
			if conn is None:
				return None
			
			flags = fcntl.fcntl(conn, fcntl.F_GETFL)
			if not conn.closed:
				fcntl.fcntl(conn, fcntl.F_SETFL, flags| os.O_NONBLOCK)
			
			try:
				if not select([conn], [], [], 0)[0]:
					return ''
				
				r = conn.read(maxsize)
				if not r:
					return self._close(which)
	
				if self.universal_newlines:
					r = self._translate_newlines(r)
				return r
			finally:
				if not conn.closed:
					fcntl.fcntl(conn, fcntl.F_SETFL, flags)

