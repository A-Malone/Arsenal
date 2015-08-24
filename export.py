import urllib3
import certifi

import json

import sqlite3

import traceback
import math
from collections import defaultdict
# Init

conn = sqlite3.connect('database.db')
c = conn.cursor()
try:
	data = {"5.11":{}, "5.14":{}}
	# Nodes
	def exportNodes(version):
		c.execute('''SELECT itemStat.version, itemStat.id, item.name, itemStat.winRate
			FROM itemStat
			LEFT JOIN item ON itemStat.version = item.version AND itemStat.id = item.id
			WHERE itemStat.version = ?
			''', (version,))
		def nodesToDict(node):
			return {
				'version' : node[0],
				'id' : node[1],
				'name' : node[2],
				'winRate': node[3]
			}
		data[version]['nodes'] = list(map(nodesToDict, c.fetchall()))
	# Links
	def exportLinks(version):
		c.execute('''SELECT [match].version,
	       item1 AS item1Id,
	       item2 AS item2Id,
	       CAST (COUNT() AS FLOAT) / (
	                                     SELECT COUNT(DISTINCT id) 
	                                       FROM [match]
	                                 )
	  FROM (
	           SELECT i1.matchId,
	                  i1.participantId,
	                  i1.itemId AS item1,
	                  i2.itemId AS item2
	             FROM participantItem AS i1
	                  CROSS JOIN
	                  participantItem AS i2 ON i1.matchId = i2.matchId AND 
	                                           i1.participantId = i2.participantId AND 
	                                           i1.itemId < i2.itemId
	       )
	       LEFT JOIN
	       [match] ON matchId = [match].id
	       LEFT JOIN
	       item AS item1 ON [match].version = item1.version AND 
	                        item1 = item1.id
	       LEFT JOIN
	       item AS item2 ON [match].version = item2.version AND 
	                        item2 = item2.id
	 WHERE [match].version = ?
	 GROUP BY [match].version,
	          item1,
	          item2
			''', (version,))
		def linksToDict(link):
			return {
				'version' : link[0],
				'source' : link[1],
				'target' : link[2],
				'value' : link[3]
			}
		data[version]['links'] = list(map(linksToDict, c.fetchall()))
	exportNodes('5.11')
	exportNodes('5.14')
	exportLinks('5.11')
	exportLinks('5.14')
	with open('itemCross.json', 'w') as f:
		f.write(json.dumps(data))
	conn.commit()
except:
	traceback.print_exc()


conn.close()
print('Done!')
input()
