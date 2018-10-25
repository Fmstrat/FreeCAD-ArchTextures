import FreeCAD, Part
import math
from functools import cmp_to_key
from pivy import coin
from itertools import groupby

DEBUG = False

globalX = FreeCAD.Vector(1, 0, 0)
globalY = FreeCAD.Vector(0, 1, 0)
globalZ = FreeCAD.Vector(0, 0, 1)

def toFreeCADVector(vector):
    return FreeCAD.Vector(vector[0], vector[1], vector[2])

def buildTriangle(vertices):
    v1 = vertices[0]['vector']
    v2 = vertices[1]['vector']
    v3 = vertices[2]['vector']

    e1 = Part.LineSegment(v1, v2)
    e2 = Part.LineSegment(v2, v3)
    e3 = Part.LineSegment(v3, v1)

    wire = Part.Wire([e1.toShape(), e2.toShape(), e3.toShape()])

    return Part.Face(wire)

def calculateNormal(face):
    uv = face.Surface.parameter(face.CenterOfMass)
    return face.normalAt(uv[0], uv[1])

def calculateTextureCoordinate(vector, boundingBox, scaleFactor, swapAxis=False):
    if swapAxis:
        vertexS = vector.z
        vertexT = vector.x

        sMax = boundingBox.ZMax
        tMax = boundingBox.XMax
    else:
        vertexS = vector.x
        vertexT = vector.z

        sMax = boundingBox.XMax
        tMax = boundingBox.ZMax
    
    scaleS = scaleFactor[0]
    scaleT = scaleFactor[1]

    s = vertexS / sMax
    t = vertexT / tMax

    return (s * scaleS, t * scaleT)

def appendCoordinate(textureCoords, index, s, t):
    textureCoords.point.set1Value(index, s, t)

class Face():
    def __init__(self):
        self.indices = []
        self.vertices = []
        self.originalVertices = []

        if DEBUG:
            self.atOriginVertices = []
            self.rotatedVertices = []
            self.positiveTransform = None
    
    def addVertex(self, index, vect):
        if index not in self.indices:
            self.indices.append(index)

            self.originalVertices.append({
                'index': index,
                'vector': toFreeCADVector(vect.getValue())
            })
            
            self.vertices.append({
                'index': index,
                'vector': toFreeCADVector(vect.getValue())
            })

            self.length = 0
            self.height = 0
    
    def appendTextureCoordinates(self, textureCoords, realSize):
        axisSwapped = self.shouldSwapAxis(realSize)
        scaleFactor = self.calculateScaleFactor(realSize, axisSwapped)

        for vertex in self.vertices:
            s, t = calculateTextureCoordinate(vertex['vector'], self.boundingBox, scaleFactor, axisSwapped)
            appendCoordinate(textureCoords, vertex['index'], s, t)
    
    def calculateScaleFactor(self, realSize, axisSwapped=False):
        tScale = 1
        sScale = 1

        if axisSwapped:
            s = self.height
            t = self.length
        else:
            s = self.length
            t = self.height

        if realSize is not None:
            realS = realSize['s']

            if realS > 0:
                sScale = s / realS
            
            realT = realSize['t']

            if realT > 0:
                tScale = t / realT

        return [sScale, tScale]
    
    def shouldSwapAxis(self, realSize):
        longestTextureAxis = 's'
        longestFaceAxis = 's'

        if realSize is not None:
            if realSize['t'] > realSize['s']:
                longestAxis = 't'
        
        if self.height > self.length:
            longestFaceAxis = 't'

        shouldSwap = longestTextureAxis != longestFaceAxis

        return shouldSwap
    
    def finishFace(self):
        # The first three vertices form the first triangle.
        # We use this information to get the normal and the offset from the origin
        # of the whole face

        # Calculations based on http://www.meshola.com/Articles/converting-between-coordinate-systems
        offsetVector = self.vertices[0]['vector']
        self.moveToOrigin(offsetVector)

        originTriangle = buildTriangle(self.vertices)
        matrix = self.calculateRotationMatrix(originTriangle)

        self.rotate(matrix)
        self.moveToPositiveAxis()

        self.boundingBox = self.calculateBoundBox()
        self.length = self.boundingBox.XLength
        self.height = self.boundingBox.ZLength

    def calculateBoundBox(self):
        xValues = [vertex['vector'][0] for vertex in self.vertices]
        yValues = [vertex['vector'][1] for vertex in self.vertices]
        zValues = [vertex['vector'][2] for vertex in self.vertices]

        xMin = min(xValues)
        yMin = min(yValues)
        zMin = min(zValues)
        xMax = max(xValues)
        yMax = max(yValues)
        zMax = max(zValues)

        return FreeCAD.BoundBox(xMin, yMin, zMin, xMax, yMax, zMax)

    def moveToPositiveAxis(self):
        '''Move the face to the positive x and z values'''
        
        boundingBox = self.calculateBoundBox()

        xMin = boundingBox.XMin
        zMin = boundingBox.ZMin

        transformVector = FreeCAD.Vector()

        if xMin < 0:
            transformVector.x = xMin * -1
        
        if zMin < 0:
            transformVector.z = zMin * -1

        if transformVector.Length == 0:
            # No transformations needed
            return

        if DEBUG:
            self.positiveTransform = (xMin, zMin, transformVector)

        for vertex in self.vertices:
            if DEBUG:
                self.rotatedVertices.append({
                    'index': vertex['index'],
                    'vector': vertex['vector']
                })

            v = vertex['vector']
            vertex['vector'] = v.add(transformVector)

    def calculateRotationMatrix(self, triangle):
         # The face normal should point toward the front view
        localY = calculateNormal(triangle)
        # as the first point is now in the origin, find the second point.
        # Should not be the diagonal point of the triangle.
        localX = FreeCAD.Vector(self.findLocalXAxis())
        # last axis is the cross product of the other two
        localZ = localY.cross(localX)

        # normalize the vectors. Otherwise we will scale our rotated triangle.
        normalizedX = localX.normalize()
        normalizedY = localY.normalize()
        normalizedZ = localZ.normalize()

        return FreeCAD.Matrix(normalizedX.dot(globalX), normalizedX.dot(globalY), normalizedX.dot(globalZ), 0,
                              normalizedY.dot(globalX), normalizedY.dot(globalY), normalizedY.dot(globalZ), 0,
                              normalizedZ.dot(globalX), normalizedZ.dot(globalY), normalizedZ.dot(globalZ), 0,
                              0, 0, 0, 1)


    def moveToOrigin(self, offsetVector):
        '''To move the face to the origin we simply subtract the first vertex from every vertex.'''
        for vertex in self.vertices:
            v = vertex['vector']
            vertex['vector'] = v.sub(offsetVector)
    
    def rotate(self, matrix):
        for vertex in self.vertices:
            if DEBUG:
                self.atOriginVertices.append({
                    'index': vertex['index'],
                    'vector': vertex['vector']
                })

            v = vertex['vector']
            vertex['vector'] = matrix.multiply(v)
    
    def findLocalXAxis(self):
        origin = self.vertices[0]['vector']
        v1 = self.vertices[1]['vector']
        v2 = self.vertices[2]['vector']

        distanceToV1 = origin.distanceToPoint(v1)
        distanceToV2 = origin.distanceToPoint(v2)

        if distanceToV1 < distanceToV2:
            return v1
        
        return v2

    def printData(self, realSize=None):
        if DEBUG:
            print('   atOriginVertices:')
            for vertex in self.atOriginVertices:
                print('    %s' % (vertex, ))

            print('   rotatedVertices:')
            for vertex in self.rotatedVertices:
                print('    %s' % (vertex, ))
        

            print('   vertices:')
            for vertex in self.vertices:
                print('    %s' % (vertex, ))
            
            print('    positiveTransform: %s' % (self.positiveTransform, ))
            print('    swapAxis: %s' % (self.shouldSwapAxis(realSize), ))

        textureCoords = coin.SoTextureCoordinate2()
        self.appendTextureCoordinates(textureCoords, realSize)

        normalizedCoords = coin.SoTextureCoordinate2()
        self.appendTextureCoordinates(normalizedCoords, None)

        print('   originalVertices:')
        for vertex in self.originalVertices:
            normalizedIndexCoords = normalizedCoords.point.getValues()[vertex['index']].getValue()
            indexCoords = textureCoords.point.getValues()[vertex['index']].getValue()

            print('    %s' % ({
                'index': vertex['index'],
                'vector': vertex['vector'],
                'normalizedCoords': normalizedIndexCoords,
                'coords': indexCoords
            }, ))
 
        print('    length: %s, height: %s' % (self.length, self.height))
        print('    scaleFactor: %s' % (self.calculateScaleFactor(realSize), ))

class FaceSet():
    def __init__(self):
        self.faces = []
    
    def addFace(self, faceCoordinates, vertices):
        face = Face()

        for coordinate in faceCoordinates:
            for index in coordinate:
                face.addVertex(index, vertices[index])
        
        face.finishFace()

        self.faces.append(face)
    
    def calculateTextureCoordinates(self, realSize):
        textureCoords = coin.SoTextureCoordinate2()

        for face in self.faces:
            face.appendTextureCoordinates(textureCoords, realSize)

        return textureCoords
    
    def printData(self, realSize=None, faceNumber=None):
        if faceNumber is not None:
            print('Face:')
            self.faces[faceNumber].printData(realSize)
        else:
            for face in self.faces:
                print('Face:')
                face.printData(realSize)
    
def findVertexCoordinates(node):
     for child in node.getChildren():
        if child.getTypeId().getName() == 'Coordinate3':
            return child

def findSwitch(node):
    for child in node.getChildren():
        if child.getTypeId().getName() == 'Switch':
            return child

def findShadedNode(node):
    children = node.getChildren()

    if children is None or children.getLength() == 0:
        return None
    
    for child in children:
        if child.getTypeId().getName() == 'SoBrepFaceSet':
            return node
        
        shadedNode = findShadedNode(child)

        if shadedNode is not None:
            return shadedNode

def findBrepFaceset(node):
    children = node.getChildren()

    if children is None or children.getLength() == 0:
        return None
    
    for child in children:
        if child.getTypeId().getName() == 'SoBrepFaceSet':
            return child
    
    return None

def buildFaceCoordinates(brep):
    triangles = []
    faces = []

    groups = groupby(brep.coordIndex, lambda coord: coord == -1)
    triangles = [tuple(group) for k, group in groups if not k]

    nextTriangle = 0

    for triangleCount in brep.partIndex:
        faces.append(triangles[nextTriangle:nextTriangle + triangleCount])
        nextTriangle += triangleCount

    return faces

def buildFaceSet(brep, vertexCoordinates):
    faceSet = FaceSet()
    
    faceCoordinateList = buildFaceCoordinates(brep)
    vertexValues = vertexCoordinates.point.getValues()

    for faceCoordinates in faceCoordinateList:
        faceSet.addFace(faceCoordinates, vertexValues)

    return faceSet


if __name__ == "__main__":
    def printValues(l):
        values = []

        for index, e in enumerate(l):
            print('%s: %s' % (index, e.getValue()))
    
    rootNode = FreeCAD.ActiveDocument.Wall.ViewObject.RootNode
    switch = findSwitch(rootNode)
    brep = findBrepFaceset(switch)
    vertexCoordinates = findVertexCoordinates(rootNode)
    
    faceSet = buildFaceSet(brep, vertexCoordinates)
    faceSet.printData({'s': 1680, 't': 1440})
    # printValues(textureCoords.point.getValues())