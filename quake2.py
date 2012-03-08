import logging
import os
import subprocess
import sys
import re
import threading
import time

from Queue import Queue

QCONSOLE_POLL_INTERVAL = 0.5

class DmFlags(object):
	NO_HEALTH = 1
	NO_POWERUPS = 2
	WEAPONS_STAY = 4
	NO_FALL_DAMAGE = 8
	INSTANT_POWERUPS = 16
	SAME_MAP = 32
	TEAMS_BY_SKIN = 64
	TEAMS_BY_MODEL = 128
	NO_FRIENDLY_FIRE = 256
	SPAWN_FARTHEST = 512
	FORCE_RESPAWN = 1024
	NO_ARMOR = 2048
	ALLOW_EXIT = 4096
	INFINITE_AMMO = 8192
	QUAD_DROP = 16384
	FIXED_FOV = 32768

class Server(object):

	def __init__(self, config):
		self.logf = logging.getLogger('Quake2')
		
		self.q2ded = config['path.q2ded']
		self.baseq2 =  config['path.baseq2']
		self.port = config['quake2.port']
		
		self.clients = {}

	def clearConsole(self):
		
		consolePath = self.baseq2 + os.sep + 'qconsole.log'
		if os.path.exists(consolePath):
			self.logf.debug('Removing existing Quake2 console log')
			os.unlink(consolePath)
		open(consolePath, 'w').close()
		
	def openConsole(self):
		
		# Open the console
		self.consolePos = 0
		self.pollingThread = threading.Thread(name='Q2ConsolePoller',
											target=self.pollConsole)
		self.pollingThread.start()

	def pollConsole(self):

		logf = logging.getLogger('Q2Console')
		while self.pollingThread:
			
			consolef = open(self.baseq2 + os.sep + 'qconsole.log', 'r')
			consolef.seek(self.consolePos)
		
			# Keep reading until we have no events
			for line in consolef:
				
				handler, match = self.parseConsoleMessage(line)
				if handler:
					msg = handler(match)
					if msg:
						logf.info('\t%s', msg.rstrip())
					else:
						logf.debug('\t%s', line.rstrip())
				else:
					logf.debug('\t%s', line.rstrip())
				
			self.consolePos = consolef.tell()
			consolef.close()
			time.sleep(QCONSOLE_POLL_INTERVAL)

		if not consolef.closed:
			consolef.close()

	def closeConsole(self):
		
		poller = self.pollingThread
		self.pollingThread = None
		poller.join()
		
	def parseConsoleMessage(self,msg):
		
		def message(s):
			return re.compile( s.replace('__', '[^ ]+') + '\\n' )
	
		messageTemplates = [
			 # Frag messages
			 (message('(__)( was blasted by )(__)'), self.fragMessage),
			 (message('(__)( was gunned down by )(__)'), self.fragMessage),
			 (message('(__)( was blown away by )(__)(\'s super shotgun)'), self.fragMessage),
			 (message('(__)( was machinegunnged by )(__)'), self.fragMessage),
			 (message('(__)( was cut in half by )(__)(\'s chaingun)'), self.fragMessage),
			 (message('(__)( was popped by )(__)(\'s grenade)'), self.fragMessage),
			 (message('(__)( ate )(__)(\'s rocket)'), self.fragMessage),
			 (message('(__)( almost dodged )(__)(\'s rocket)'), self.fragMessage),
			 (message('(__)( was melted by )(__)(\'s hyperblaster)'), self.fragMessage),
			 (message('(__)( was railed by )(__)'), self.fragMessage),
			 (message('(__)( saw the pretty lights from )(__)(\'s BFG)'), self.fragMessage),
			 (message('(__)( was disintegrated by )(__)(\'s BFG blast)'), self.fragMessage),
			 (message('(__)( couldn\'t hide from )(__)(\'s BFG)'), self.fragMessage),
			 (message('(__)( caught )(__)(\'s handgrenade)'), self.fragMessage),
			 (message('(__)( didn\'t see )(__)(\'s handgrenade)'), self.fragMessage),
			 (message('(__)( feels )(__)(\'s pain)'), self.fragMessage),
			 (message('(__)( tried to invade )(__)(\'s personal space)'), self.fragMessage),
			 
			 # Suicide messages
			 (message('(__)( suicides)'), self.suicideMessage),
			 (message('(__)( cratered)'), self.suicideMessage),
			 (message('(__)( was squished)'), self.suicideMessage),
			 (message('(__)( sank like a rock)'), self.suicideMessage),
			 (message('(__)( melted)'), self.suicideMessage),
			 (message('(__)( does a back flip into the lava)'), self.suicideMessage),
			 (message('(__)( blew up)'), self.suicideMessage),
			 (message('(__)( found a way out)'), self.suicideMessage),
			 (message('(__)( saw the light)'), self.suicideMessage),
			 (message('(__)( was in the wrong place)'), self.suicideMessage),
			 (message('(__)( tried to put the pin back in)'), self.suicideMessage),
			 (message('(__)( tripped on (its|her|his) own grenade)'), self.suicideMessage),
			 (message('(__)( blew (itself|herself|himself) up)'), self.suicideMessage),
			 (message('(__)( should have used a smaller gun)'), self.suicideMessage),
			 (message('(__)( killed (itself|herself|himself))'), self.suicideMessage),
			 
			 
			 # Server messages
			 (message('-------- Server Initialized ---------'), self.serverInitialized),
			 (message('-------------------------------------'), self.serverInitialized)
			 ]
		
		# Match the message against the known Quake2 message templates
		for (expr,handler) in messageTemplates:
			
			match = expr.match(msg)
			if match:
			   return handler, match
		
		return None,None
		
	## MESSAGE HANDLERS #######################################################
	
	def serverInitialized(self,match):
		
		self.readyQueue.put('ready')
	
	def timelimitHit(self,match):
		
		self.logf.info('Timelimit has been hit, ending game')
		self.endGame()
	
	def fraglimitHit(self,match):
		
		self.logf.info('Fraglimit has been hit, ending game')
		self.endGame()
		
	def suicideMessage(self,match):

		try:
			# Lookup the bot who died
			targ = self.clients[match.group(1)]
			targ.stats.suicides = targ.stats.suicides + 1
			
			return "%s died." % targ.name
		except:
			self.logf.warning('Unknown suicide: %s', match.group(1))
			
	def fragMessage(self,match):
		
		try:
			# Lookup the involved parties
			targ = self.clients[match.group(1)]
			attacker = self.clients[match.group(3)]
		
			# Update stats
			targ.stats.deaths = targ.stats.deaths + 1
			attacker.stats.frags = attacker.stats.frags + 1
		
			return "%s killed %s." % (attacker.name, targ.name)
		
		except:
			self.logf.warning('Unknown attacker or target: %s/%s', match.group(3), match.group(1))

	def launch(self,options,map):
		"""
		Launches the quake2 dedicated server and starts up a polling thread
		to parse the console output.		
		"""
		self.readyQueue = Queue(1)
		
		# Compute the command line args
		args = [ self.q2ded, '+map', map ]
		options['basedir'] = os.path.dirname(self.q2ded)
		options['logfile'] = '2'
		options['dedicated'] = '1'
		
		self.logf.info('Game parameters: ')
		for opt,value in options.iteritems():
			args.append( '+set')
			args.append('%s' % opt)
			args.append('%s' % value)

			self.logf.info('\t%s:\t%s', opt, value)
		
		self.clearConsole()
		self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=open('/dev/null'), stderr=open('/dev/null'))
		self.logf.info('Launched quake2 with pid = %d', self.proc.pid)
		self.openConsole()

		# Wait for Quake2 to initialize
		return self.readyQueue.get()

	def kill(self):
		"""
		Disconnects all clients and brings down the quake2 server.
		"""
		
		if not self.proc:
			self.logf.error('Received kill request, but I am not aware of any quake2 server running!')
			return
		
		if self.proc.poll():
			self.logf.error('Received kill request, but the server has already stopped!')
			self.proc = None
			return
		
		self.logf.info('Kill request received, disconnecting clients...')
		for bot in self.clients.itervalues():
			try:
				bot.disconnect()
				bot.quit()
			except:
				self.logf.error("bot: %s is defucnt, continuing" % bot.name)
			self.logf.info('\t%s left game', bot.name)
		
		self.closeConsole()
		
		self.logf.info('Stopping quake2...')
		self.proc.stdin.write('quit\r\n')
		self.proc.wait()

		self.proc.stdin.close()
		#self.proc.stdout.close()
		#self.proc.stderr.close()

		self.proc = None
		self.logf.info('\tQuake2 is stopped')

	def runGame(self,timelimit,entrants):

		self.logf.info('Launching bots:')
		
		# Launch the bots:
		self.clients.clear()
		for bot in entrants:

			bot.launch()
			self.logf.info('\t%s:\tlaunched', bot.name)
			
			bot.connect('localhost', str(self.port))

			self.logf.info('\t%s:\tconnected', bot.name)
			self.clients[bot.name] = bot
			
		self.logf.info('All bots have entered the game, starting the competition')
		
		# Start the game.
		for bot in self.clients.itervalues():
			self.logf.debug('Starting %s', bot.name)
			bot.start()

		# Wait for the time to expire
		time.sleep( 60.0 * timelimit )

		self.logf.info('Time is up, ending game')
		
		# Stop the bots from fighting first; the disconnect operation may
		# take a few seconds, this will prevent any from gaining an unfair
		# advantage by continuing to frag while waiting to be disconnected
		for bot in self.clients.itervalues(): 
			self.logf.debug('Stopping %s', bot.name)
			bot.stop()
		
		# Now disconnect and quit each bot one by one.
		for bot in self.clients.itervalues():
			
			self.logf.info('\t%s:\tdisconnecting', bot.name)
			bot.disconnect()
			self.logf.debug('\t\t\tquitting')
			bot.quit()
			self.logf.debug('\t\t\tok')

		# Return a list of bot stats to the caller
		return map(lambda bot: bot.stats, self.clients.itervalues())
