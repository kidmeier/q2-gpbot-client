import logging
import platform
import socket
import sys
import time
import asyncPipe

import quake2

from bot import Bot
from build import Builder

MAX_BOTS = 16
SERVER_RETRY_TIMEOUT = 30.0

class Main(object):

	def __init__(self):
		self.logf = logging.getLogger('Main')
		
		self.configPath = 'config/' + platform.system() + '.conf'
		self.initPlatformConfig()
		
		self.builder = Builder(self.config)
		self.q2ded = quake2.Server(self.config)
		#TODO self.quake2 = quake2.Client(self.config)
		
		self.running = True
	
	def initPlatformConfig(self):
	
		# Load the configuration dictionary
		try:
			self.logf.info('Loading default configuration')
			
			# First read defaults
			fp = open('config/defaults.conf')
			self.config = eval(''.join(fp.readlines()))
			fp.close()
			
			self.logf.info('Loading platform configuration from %s', self.configPath)
			
			# Now load the platform config to override defaults where necessary
			fp = open(self.configPath)
			self.config.update(eval(''.join(fp.readlines())))

			# Log the platform configuration info
			self.logf.info('Platform config:')
			for k,v in self.config.iteritems():
				self.logf.info('\t%s = %s' % (k,str(v)))
			
		except:
			self.logf.critical('Failed to load platform config: %s', self.configPath, exc_info=True)
			sys.exit(1)

		finally:
			if fp:
				fp.close()
	
	def launchQuake(self):
		self.q2ded.launch({
				'timelimit':0,
				'fraglimit':0,
				'maxclients':MAX_BOTS+1,	# +1 for a spectator
				'dmflags':quake2.DmFlags.INSTANT_POWERUPS	# No inventory for simplicity
						+ quake2.DmFlags.FORCE_RESPAWN		# Bots that aren't firing should come back if they die
						+ quake2.DmFlags.SPAWN_FARTHEST		# This prevents telefrags
			},
			'tsm_dm1')
		
	def run(self):
			
		# Launch the quake2 dedicated server	
		self.launchQuake()
		
		gameCount = 0
		
		# Keep polling the server for 
		while self.running:
			
			self.logf.info('Starting a new game. gameCount = %d', gameCount)
			token = self.getBots()
			
			if token:
				self.compileBots()
				try:
					self.runGame()
				except:
					self.logf.error('Error encountered, results discarded, resetting')
					asyncPipe.processList.cleanupProcesses()
					self.q2ded.kill()
					self.launchQuake()
				else:
					self.postResults(token)
					self.cleanUp()
				
					gameCount = gameCount + 1
			else:
				self.logf.warning('No bots received from server, trying again in %d s', SERVER_RETRY_TIMEOUT)
				time.sleep(SERVER_RETRY_TIMEOUT)

		# Stop the server
		self.q2ded.kill()
	
	def getBots(self):
		"""
		Connect to the q2 bot server (Will) to retrieve the next group of bots
		to compete. The protocol is simple text as follows:
		
		1.	CONNECT
		2.	SEND: GETBOTS\n
		3.	RECV: token\n
		4.	RECV: STARTBOT botName\n
		4.	RECV: stmt\n
		5.	Repeat #4 until: stmt = ENDBOT id\n
		"""
		self.bots = []
		input = None
		s = socket.socket()
		try:
			self.logf.info('Connecting to %s:%d', self.config['gp.host'], self.config['gp.port'])
			s.connect((self.config['gp.host'],self.config['gp.port']))

			self.logf.debug('GETBOTS')
			s.sendall('GETBOTS\n')
			input = s.makefile('r')
			token = input.readline().rstrip()
			
			if not token:
				self.logf.error('Received null token')
				return None
			
			if len(token) <= 0:
				self.logf.error('Received empty token')
				return None
			
			self.logf.info('Received token %s', token)
			for line in input:
				botName = line.rstrip().split()[1]
				code = ''
				for stmt in input:
					if stmt.startswith('ENDBOT %s' % botName):
						bot = Bot(botName, code)
						self.logf.info('Received bot %s\t(%d lines)', botName, len(code.split('\n')))
						self.bots.append( bot )
						break
					
					# Continue to build the bot
					self.logf.debug(stmt.rstrip())
					code = code + stmt
					
			return token
		
		except:
			self.logf.error('Caught exception while retrieving bots:', exc_info=True)
						
		finally:
			s.close()
			if input:
				input.close()
		
		return None
	
	def compileBots(self):
		self.logf.info('Compiling:')
		for bot in self.bots:
			self.logf.info('\t%s', bot.name)
			self.builder.compile(bot)

	def cleanUp(self):
		for bot in self.bots:
			self.builder.clean(bot)
		
	def runGame(self):
		
		self.q2ded.runGame(2.0, self.bots)
	
	def postResults(self,token):
		
		try:
			self.logf.info('Posting results to %s:%d with token %s', self.config['gp.host'], self.config['gp.port'], token)
			s = socket.socket()
			s.connect((self.config['gp.host'], self.config['gp.port']))
			s.sendall('POSTRESULTS\n')
			s.sendall(token + '\n')
			for bot in self.bots:
				fitness = bot.stats.computeFitness()
				self.logf.info('\t%s:\tfitness = %f', bot.name, fitness)
				s.sendall('%f %s\n' % (fitness, bot.name))

		except:
			self.logf.warning('Failed to post results to bot server:', exc_info=True)

		finally:
			if s:
				s.close()

################################ Main ##########################################

# Set up our logging config
logging.basicConfig(level=logging.INFO,
					format='%(asctime)s %(name)6s:%(levelname)-7s %(message)-40s (%(filename)s:%(lineno)s)',
					filename='GPclient.log',
					filemode='w')
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter('%(name)8s: %(levelname)-8s %(message)s'))
logging.getLogger('').addHandler(console)

# Go!
Main().run()
