import urllib3
import certifi

import json

import sqlite3

import traceback
import math
from collections import defaultdict
# Init
http = urllib3.PoolManager(
	cert_reqs='CERT_REQUIRED',  # Force certificate check.
	ca_certs=certifi.where(),  # Path to the Certifi bundle.
)
conn = sqlite3.connect('database.db')
c = conn.cursor()

# Some useful views
try:
	c.execute('''CREATE VIEW eventItem AS
	    SELECT matchId,
	           type,
	           timestamp,
	           item.name
	      FROM event
	           LEFT JOIN
	           [match] ON event.matchId = [match].id
	           LEFT JOIN
	           item ON [match].version = item.version AND 
	                   event.itemId = item.id
	     ORDER BY timestamp;''')
	c.execute('''CREATE VIEW participantItemStatic AS
	    SELECT matchId,
	           participantId,
	           itemId,
	           name,
	           flatAp
	      FROM participantItem
	           LEFT JOIN
	           [match] ON participantItem.matchId = [match].id
	           LEFT JOIN
	           item ON [match].version = item.version AND 
	                   participantItem.itemId = item.id''')
	# Items bought
	c.execute('''SELECT matchId, id FROM participant''')
	for (matchId, participantId) in c.fetchall():
		c.execute('''SELECT event.type, event.timestamp, event.itemId, frame.*
			FROM event
			LEFT JOIN match ON event.matchId = match.id
			LEFT JOIN frame ON event.matchId = match.id AND event.frameId = frame.id
			LEFT JOIN item ON match.version = item.version AND event.itemId=item.id
			WHERE match.id = ? AND event.participantId = ? AND (event.type = "ITEM_PURCHASED" OR event.type = "ITEM_DESTROYED" OR event.type = "ITEM_SOLD")
			ORDER BY timestamp''',
			(matchId, participantId))
		items = []
		for (eventType, timestamp, itemId, goldThreshold) in c.fetchall():
			if eventType == 'ITEM_PURCHASED':
				items.append((itemId, timestamp, goldThreshold))
			elif eventType == 'ITEM_DESTROYED' or eventType == 'ITEM_SOLD':
				items.pop([x for x in zip(*items)][0].index(itemId))
		for (itemId, timeBought, goldThreshold) in items:
			c.execute('''INSERT INTO participantItem (matchId, participantId, itemId, timeBought, goldThreshold)
				VALUES (?, ?, ?, ?, ?)''',
				(matchId, participantId, itemId, timeBought, goldThreshold))
	print('Items bought.')
	# Resolve stacks
	# RoA
	c.execute('''SELECT matchId, participantId, timeBought
		FROM participantItem
		WHERE participantItem.itemId = 3027
		GROUP BY matchId''')
	storedMatchId = -1
	for (matchId, participantId, timeBought) in c.fetchall():
		# Cache matchDuration to minimize additional queries
		if matchId != storedMatchId:
			c.execute('''SELECT duration
				FROM match
				WHERE id = ?''', (matchId,))
			storedMatchId = matchId
			matchDuration = c.fetchone()[0]
		# Calculate the final number of stacks
		finalStacks = min(matchDuration // 60 - timeBought // 1000 // 60, 20)
		# Update the table
		c.execute('''UPDATE participantItem
			SET finalStacks = ?, maxStacks = ?
			WHERE matchId = ? AND participantId = ? AND itemId = 3027''',
			(finalStacks, finalStacks, matchId, participantId))
		# Multiple of the same item bought? Need SQLITE_enable_update_delete_limit
		# c.execute('''UPDATE participantItem SET finalStacks = ?, maxStacks = ?
		# 	WHERE matchId = ? AND participantId = ? AND itemId = 3027
		# 	ORDER BY timeBought
		# 	LIMIT 1''',
		# 	(finalStacks, maxStacks, matchId, participantId))
	# Mejais
	class finalStacks:
		def __init__(self):
			self.stacks = 6
		def step(self, participantId, killerId, victimId, assistId):
			if participantId == killerId:
				self.stacks = min(self.stacks + 2, 20)
			elif participantId == victimId:
				self.stacks //= 2
			elif participantId == assistId:
				self.stacks = min(self.stacks + 1, 20)
			else:
				print(participantId, killerId, victimId, assistId)
				raise 'Error'
		def finalize(self):
			return self.stacks
	conn.create_aggregate("finalStacks", 4, finalStacks)
	class maxStacks:
		def __init__(self):
			self.stacks = 6
			self.maxStacks = self.stacks
		def step(self, participantId, killerId, victimId, assistId):
			if participantId == killerId:
				self.stacks = min(self.stacks + 2, 20)
			elif participantId == victimId:
				self.stacks //= 2
			elif participantId == assistId:
				self.stacks = min(self.stacks + 1, 20)
			else:
				print(participantId, killerId, victimId, assistId)
				raise 'Error'
			self.maxStacks = max(self.stacks, self.maxStacks)
		def finalize(self):
			return self.maxStacks
	conn.create_aggregate("maxStacks", 4, maxStacks)
	c.execute('''SELECT matchId, participantId, timeBought
		FROM participantItem
		WHERE participantItem.itemId = 3041
		GROUP BY matchId''')
	for (matchId, participantId, timeBought) in c.fetchall():
		# Calculate the final number of stacks
		c.execute('''SELECT ?, event.killerId, event.victimId, assist.participantId
			FROM event
			LEFT JOIN (
				SELECT assist.matchId, assist.eventId, assist.participantId
				FROM assist
				WHERE assist.participantId = ?
				) AS assist ON event.matchId = assist.matchId AND event.id = assist.eventId
			WHERE event.type == 'CHAMPION_KILL' AND event.timestamp > ? AND
			(event.killerId == ? OR event.victimId == ? OR assist.participantId == ?)
			ORDER BY event.timestamp''',
			(participantId, participantId, timeBought, participantId, participantId, participantId))
		c.execute('''SELECT
			finalStacks(?, event.killerId, event.victimId, assist.participantId),
			maxStacks(?, event.killerId, event.victimId, assist.participantId)
			FROM event
			LEFT JOIN assist ON event.matchId = assist.matchId AND event.id = assist.eventId
			WHERE event.type == 'CHAMPION_KILL' AND event.timestamp > ? AND
			(event.killerId == ? OR event.victimId == ? OR assist.participantId == ?)
			ORDER BY event.timestamp''',
			(participantId, participantId, timeBought, participantId, participantId, participantId))
		finalStacks, maxStacks = c.fetchone()
		# Update database
		c.execute('''UPDATE participantItem
			SET finalStacks = ?, maxStacks = ?
			WHERE matchId = ? AND participantId = ? AND itemId = 3041''',
			(finalStacks, maxStacks, matchId, participantId))
	print('Item stacks resolved')

	# Item AP
	c.execute('''SELECT participant.matchId, participant.id, TOTAL(item.flatAp + participantItem.finalStacks * 20), MAX(item.percentAp)
		FROM participant
		LEFT JOIN participantItem ON participant.matchId = participantItem.matchId AND participant.id = participantItem.participantId
		LEFT JOIN item ON participantItem.itemId = item.id
		GROUP BY participant.matchId, participant.id''')
	# WHERE participantItem.stacks = 0 OR participantItem.itemId = RoA OR Mejai	
	for (matchId, participantId, totalFlatItemAp, totalPercentItemAp) in c.fetchall():
		c.execute('''UPDATE participant
			SET totalFlatItemAp = ?, totalPercentItemAp = ?
			WHERE participant.matchId = ? AND participant.id = ?''',
			(totalFlatItemAp, totalPercentItemAp, matchId, participantId))
	# Rune AP
	c.execute('''SELECT participant.matchId, participant.id, TOTAL(rune.flatAp), TOTAL(rune.percentAp)
		FROM participant
		LEFT JOIN participantRune ON participant.matchId = participantRune.matchId AND participant.id = participantRune.participantId
		LEFT JOIN rune ON participantRune.runeId = rune.id
		GROUP BY participant.matchId, participant.id''')
	for (matchId, participantId, totalFlatRuneAp, totalPercentRuneAp) in c.fetchall():
		c.execute('''UPDATE participant
			SET totalFlatRuneAp = ?, totalPercentRuneAp = ?
			WHERE participant.matchId = ? AND participant.id = ?''',
			(totalFlatRuneAp, totalPercentRuneAp, matchId, participantId))
	# Mastery AP
	c.execute('''SELECT participant.matchId, participant.id, TOTAL(mastery.flatAp), TOTAL(mastery.percentAp)
		FROM participant
		LEFT JOIN participantMastery ON participant.matchId = participantMastery.matchId AND participant.id = participantMastery.participantId
		LEFT JOIN mastery ON participantMastery.masteryId = mastery.id AND participantMastery.rank = mastery.rank
		GROUP BY participant.matchId, participant.id''')
	for (matchId, participantId, totalFlatMasteryAp, totalPercentMasteryAp) in c.fetchall():
		c.execute('''UPDATE participant
			SET totalFlatMasteryAp = ?, totalPercentMasteryAp = ?
			WHERE participant.matchId = ? AND participant.id = ?''',
			(totalFlatMasteryAp, totalPercentMasteryAp, matchId, participantId))
	# Total AP
	c.execute('''UPDATE participant
		SET totalAp = (
			SELECT (totalFlatItemAp + totalFlatRuneAp + totalFlatMasteryAp) *
			(1 + (totalPercentItemAp + totalPercentRuneAp + totalPercentMasteryAp) / 100)
			FROM participant AS p
			WHERE participant.matchId = p.matchId AND participant.id = p.id
			)
	''')
	print('Total AP calculated')

	class getBuildType:
		# 3006: Zerks
		# 3153: BotRK
		# 3072: BT
		# 3035: LW
		# 3031: IE
		# 3046: PD
		adItems = set([3006, 3153, 3072, 3035, 3031, 3046])
		# 3001: Abyssal
		# 3027: RoA
		# 3157: Hourglass
		# 3165: Morello
		# 3089: DCap
		# 3151: Liandry
		# 3116: Rylai
		# 3036: Seraph
		# 3041: Mejai
		apItems = set([3001, 3027, 3157, 3165, 3089, 3151, 3116, 3036, 3041])
		EPSILON = 1
		def __init__(self):
			self.apItemCount = 0
			self.adItemCount = 0
		def step(self, championId, itemId):
			if itemId in self.apItems:
				self.apItemCount += 1
			if itemId in self.adItems:
				self.adItemCount += 1
		def finalize(self):
			if self.apItemCount >= (self.adItemCount + self.EPSILON if self.adItemCount > 0 else 0):
				return 'AP'
			elif self.adItemCount >= (self.apItemCount + self.EPSILON if self.apItemCount > 0 else 0):
				return 'AD'
			return 'Undecided'
	conn.create_aggregate('getBuildType', 2, getBuildType)
	c.execute('''SELECT participant.matchId, participant.id, getBuildType(participant.championId, participantItem.itemId)
			FROM participant
			LEFT JOIN participantItem ON participant.matchId = participantItem.matchId AND participant.id = participantItem.participantId
			GROUP BY participantItem.matchId, participantItem.participantId''')
	for (matchId, participantId, buildType) in c.fetchall():
		c.execute('''UPDATE participant SET buildType = ?
			WHERE matchId = ? AND id = ?''',
			(buildType, matchId, participantId))
	print('Build types analyzed')

	# Champion stats
	c.execute('''CREATE TABLE championStat (
			version TEXT,
			championId INTEGER,
			picks INTEGER,
			bans INTEGER
			wins INTEGER,
			role TEXT,
			lane TEXT,
			buildType TEXT,
			wins INTEGER,
			kills INTEGER,
			deaths INTEGER,
			assists INTEGER,
			assassinations INTEGER,
			firstBloodKillOrAssist INTEGER,
			firstTowerKillOrAssist INTEGER,
			totalTimeCrowdControlDealt INTEGER,
			damageDealt INTEGER,
			damageDealtToChampions INTEGER,
			magicDamageDealt INTEGER,
			magicDamageDealtToChampions INTEGER,
			totalAp REAL,
			FOREIGN KEY (version, championId) REFERENCES champion(version, id)
		)''')
	c.execute('''INSERT INTO championStat (version, championId, wins, picks, kills, deaths, assists, assassinations, firstBloodKillOrAssist,
		firstTowerKillOrAssist, totalTimeCrowdControlDealt, damageDealt, damageDealtToChampions, magicDamageDealt, magicDamageDealtToChampions, totalAp)
			SELECT match.version, participant.championId, TOTAL(team.winner), TOTAL(participant.id), AVG(participant.kills), AVG(participant.deaths),
			AVG(participant.assists), AVG(participant.assassinations), AVG(participant.firstBloodKill + participant.firstBloodAssist),
			AVG(participant.firstTowerKill + participant.firstTowerAssist), AVG(participant.totalTimeCrowdControlDealt), AVG(participant.damageDealt),
			AVG(participant.damageDealtToChampions), AVG(participant.magicDamageDealt), AVG(participant.magicDamageDealtToChampions),
			AVG(participant.totalAp)
			FROM participant
			LEFT JOIN match ON participant.matchId = match.id
			LEFT JOIN team ON participant.matchId = team.matchId AND participant.teamId = team.id
			GROUP BY match.version, participant.championId''', ())
	c.execute('''UPDATE championStat
		SET bans = (SELECT COUNT(*)
			FROM ban
			LEFT JOIN match ON ban.matchId = match.id
			WHERE championStat.version = match.version AND championStat.championId = ban.championId
			)''')

	# Item stats
	c.execute('''CREATE TABLE itemStat (
			version TEXT,
			itemId INTEGER,
			timesBought INTEGER,
			winRate REAL,
			goldThreshold REAL,
			FOREIGN KEY (version, itemId) REFERENCES item(version, id)
		)''')
	c.execute('''INSERT INTO itemStat (version, itemId, timesBought, winRate, goldThreshold)
			SELECT match.version, participantItem.itemId, COUNT(*), AVG(team.winner), AVG(participantItem.goldThreshold)
			FROM participant
			LEFT JOIN participantItem ON participant.matchId = participantItem.matchId AND participant.id = participantItem.participantId
			LEFT JOIN match ON participant.matchId = match.id
			LEFT JOIN team ON participant.matchId = team.matchId AND participant.teamId = team.id
			GROUP BY match.version, participantItem.itemId''', ())
	c.execute('''UPDATE championStat
		SET bans = (SELECT COUNT(*)
			FROM ban
			LEFT JOIN match ON ban.matchId = match.id
			WHERE championStat.version = match.version AND championStat.championId = ban.championId
			)''')

	# Player stats
	c.execute('''CREATE TABLE playerChampion (
		playerId INTEGER NOT NULL REFERENCES player(id),
		championId INTEGER NOT NULL,
		version TEXT,
		picks INTEGER,
		FOREIGN KEY (championId, version) REFERENCES champion(id, version)
		)''')
	c.execute('''INSERT INTO playerChampion (playerId, championId, version, picks)
		SELECT player.id, participant.championId, match.version, COUNT(*)
		FROM player
		LEFT JOIN participant ON player.id = participant.playerId
		LEFT JOIN match ON participant.matchId = match.id
		GROUP BY player.id, participant.championId, match.version
		''')
	c.execute('''CREATE TABLE playerItem (
		playerId INTEGER REFERENCES player(id),
		itemId INTEGER NOT NULL REFERENCES item(id),
		timesBought INTEGER,
		avgTimeBought INTEGER,
		version TEXT
		)''')
	c.execute('''INSERT INTO playerItem (playerId, itemId, version, timesBought, avgTimeBought)
		SELECT player.id, participantItem.itemId, match.version, COUNT(*), AVG(participantItem.timeBought)
		FROM player
		LEFT JOIN participant ON player.id = participant.playerId
		LEFT JOIN participantItem ON participant.matchId = participantItem.matchId AND participant.id = participantItem.participantId
		LEFT JOIN match ON participant.matchId = match.id
		GROUP BY player.id, participantItem.itemId, match.version
		''')
	c.execute('''CREATE TABLE playerStat (
		playerId INTEGER REFERENCES player(id),
		version TEXT,
		gamesPlayed INTEGER,
		apPicks INTEGER,
		adPicks INTEGER)
		''')
	c.execute('''INSERT INTO playerStat (playerId, version, gamesPlayed)
		SELECT player.id, match.version, COUNT(*)
		FROM player
		LEFT JOIN participant ON player.id = participant.playerId
		LEFT JOIN match ON participant.matchId = match.id
		GROUP BY player.id, match.version
		''')
	c.execute('''UPDATE playerStat
		SET
			apPicks = (
				SELECT COUNT(*)
				FROM player
				LEFT JOIN participant ON player.id = participant.playerId
				LEFT JOIN match ON participant.matchId = match.id
				WHERE playerStat.playerId = player.id AND playerStat.version = match.version AND participant.buildType = "AP"
			),
			adPicks = (
				SELECT COUNT(*)
				FROM player
				LEFT JOIN participant ON player.id = participant.playerId
				LEFT JOIN match ON participant.matchId = match.id
				WHERE playerStat.playerId = player.id AND playerStat.version = match.version AND participant.buildType = "AD"
			)
		''')
except:
	traceback.print_exc()

conn.commit()


conn.close()
print('Done!')
input()