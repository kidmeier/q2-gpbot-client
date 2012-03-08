import asyncPipe
import os
import random
import re
import subprocess
import threading
import Queue
import logging

class Stats(object):
   
	def __init__(self):
		self.frags = 0
		self.suicides = 0
		self.deaths = 0
   
	def update(self,dict):
		self.__dict__.update(dict)

	def deathFactor(self):
		return (self.deaths + self.suicides) / (1.0 + self.deaths + self.suicides + self.frags) 

	def suicideFactor(self):
		return self.suicides / (1.0 + self.suicides + self.frags)

	def computeFitness(self):
		return (1.0 + self.frags)*(1.0 - self.deathFactor())*(1.0 - self.suicideFactor())


class Bot(object):
	"A bot received from the GP server system"

	def __init__(self, name, code):
		self.logf = logging.getLogger('Bot.%s' % name)
		self.name = name
		self.code = code
		self.stats = Stats()

		self.exe = None
		self.baseDir = None
		self.marshalling = False
		self.marshalingThread = None

	def __getattr__(self,methodName):

		# If marhsalingThread is not running then we can't
		# rightly send it any commands.
		if not self.marshalling:
			raise AttributeError, methodName
		
		if not re.match('__[a-zA-Z_][a-zA-Z0-9_]*__', methodName):
			def proxy(*args):
				
				cmdString = '%s %s' % (methodName, ' '.join(map(lambda s: str(s), args)))
				return self.proxyCall(cmdString)
			return proxy
			
		raise AttributeError, methodName

	def proxyCall(self,cmdString):
		
		self.callQueue.put(cmdString)
		try:
			result = self.returnQueue.get(timeout = 30.0)
			return result
		except Queue.Empty:
			self.logf.debug('%s command  timed out' % cmdString)
			raise SystemError
	 
	def launch(self):

		self.logf.debug('Ready to launch: cwd = %s, args = %s' % (os.path.dirname(self.exe), str([self.exe, self.name])))

		# Open the process and redirect stdout, stderr to the bot's log file
		self.proc = asyncPipe.Popen(args=[self.exe, self.name], 
								bufsize=1, 
								stdout=subprocess.PIPE,
								stdin=subprocess.PIPE,
								cwd=os.path.dirname(self.exe))
		self.callQueue = Queue.Queue(1)
		self.returnQueue = Queue.Queue(1)

		self.logf.debug('Launched bot: %s with pid = %d', self.name, self.proc.pid)

		self.logf.debug('Starting marshalling thread')
		self.marshalingThread = threading.Thread(name='%s:marshalLoop' % self.name,
												 target=self.marshalLoop)
		self.marshalingThread.start()

		# Wait for notification that the marshalling thread is ready
		self.logf.debug('Waiting for marshalling thread to become ready')
		self.returnQueue.get()
		self.logf.debug('Marshalling thread is ready to handle calls')
		
		return self.proc.pid
	
	def marshalLoop(self):
		
		try:
			self.marshalling = True
	
			# Send notification that we are ready to go
			self.returnQueue.put('ready')
			while self.proc.poll() == None:
	
				try:
					# Get a command from the call queue
					cmdString = self.callQueue.get(block=True,timeout=1.0)
					self.logf.debug('%s << %s', self.name, cmdString)
				
					# Send the cmd to the bot
					self.proc.stdin.write('%s\n' % cmdString)
	
				except Queue.Empty:
					continue
				
				# Wait for a return value
				self.proc.pollStdout(30000.0)
				line = self.proc.stdout.readline()
				
				# Pull the return value out
				result = re.match('(return )(.*)(\\n)', line).group(2)
				self.logf.debug('%s >> %s', self.name, result)
				self.returnQueue.put(result)
	
			# Cleanup
			self.marshalling = False
			self.marshalingThread = None
	
			self.proc.wait()
			self.proc.stdin.close()
			self.proc.stdout.close()
			self.proc = None
		except:
			if self.proc:
				asyncPipe.processList.killPid(self.proc.pid)
			
		
		self.logf.debug('Marshalling thread is done.')

