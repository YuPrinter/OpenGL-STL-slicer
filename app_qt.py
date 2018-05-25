import sys
from PyQt5 import QtGui, QtCore, QtWidgets
from ctypes import c_float, c_uint, sizeof
import os
from stl import mesh
import numpy as np

from printer import printer

GLfloat = c_float
GLuint = c_uint

EPSILON = 0.00001
SCR_WIDTH = 640
SCR_HEIGHT = int(SCR_WIDTH * printer.height / printer.width)


class Window(QtGui.QOpenGLWindow):
    
    def __init__(self, 
                 sltFilename, 
                 layerThickness, 
                 sliceSavePath, 
                 *args, 
                 **kwargs):
                 
        super().__init__(*args, **kwargs)
        
        # Make sure to set the Surface Format in `__init__`.
        # Otherwise, it won't work.
        format = QtGui.QSurfaceFormat()
        format.setRenderableType(QtGui.QSurfaceFormat.OpenGL)
        format.setProfile(QtGui.QSurfaceFormat.CoreProfile)
        format.setVersion(4, 1)
        format.setStencilBufferSize(8)
        self.setFormat(format)
        
        self.setTitle('STL Slicer')
        
        self.vertVAO, self.vertVBO = 0, 0
        self.maskVAO, self.maskVBO = 0, 0
        self.numOfVerts = 0
        self.bounds = dict()
        self.totalThickness = 0.
        self.currentLayer = 0
        self.height = 0
        
        self.sltFilename = sltFilename
        self.layerThickness = layerThickness
        self.sliceSavePath = sliceSavePath
        
    def initializeGL(self):
        self.gl = self.context().versionFunctions()
        
        self.shaderProg = QtGui.QOpenGLShaderProgram()
        self.shaderProg.create()
        self.shaderProg.addShaderFromSourceFile(
            QtGui.QOpenGLShader.Vertex, 'shaders/slice.vert')
        self.shaderProg.addShaderFromSourceFile(
            QtGui.QOpenGLShader.Fragment, 'shaders/slice.frag')
        self.shaderProg.link()
        
        self.loadMesh()
        
        self.proj = QtGui.QMatrix4x4()
        self.proj.setToIdentity()
        self.proj.ortho(0, printer.width*printer.pixel, 
                        0, printer.height*printer.pixel, 
                        -self.totalThickness, self.totalThickness)
                   
        self.model = QtGui.QMatrix4x4()
        self.model.setToIdentity()
        self.model.translate(0, 0, self.totalThickness+EPSILON)
        
        self.sliceFbo = QtGui.QOpenGLFramebufferObject(
            printer.width,
            printer.height
        )
        self.sliceFbo.setAttachment(
            QtGui.QOpenGLFramebufferObject.CombinedDepthStencil
        )
        
    def loadMesh(self):
        # Get information about our mesh
        ourMesh = mesh.Mesh.from_file(self.sltFilename)
        self.numOfVerts = ourMesh.vectors.shape[0] * 3
        self.bounds = {
            'xmin': np.min(ourMesh.vectors[:,:,0]),
            'xmax': np.max(ourMesh.vectors[:,:,0]),
            'ymin': np.min(ourMesh.vectors[:,:,1]),
            'ymax': np.max(ourMesh.vectors[:,:,1]),
            'zmin': np.min(ourMesh.vectors[:,:,2]),
            'zmax': np.max(ourMesh.vectors[:,:,2])
        }
        self.totalThickness = self.bounds['zmax'] - self.bounds['zmin']

        #######################################
        # make VAO for drawing our mesh
        self.vertVAO = QtGui.QOpenGLVertexArrayObject()
        self.vertVAO.create()
        self.vertVAO.bind()
    
        self.vertVBO = QtGui.QOpenGLBuffer(QtGui.QOpenGLBuffer.VertexBuffer)
        self.vertVBO.create()
        self.vertVBO.bind()
        self.vertVBO.setUsagePattern(QtGui.QOpenGLBuffer.StaticDraw)
        data = ourMesh.vectors.astype(GLfloat).tostring()
        self.vertVBO.allocate(data, len(data))
        self.gl.glVertexAttribPointer(0, 3, self.gl.GL_FLOAT, 
            self.gl.GL_FALSE, 3*sizeof(GLfloat), 0)
        self.gl.glEnableVertexAttribArray(0)
    
        self.vertVBO.release()
        self.vertVAO.release()
        #######################################
    
        # a mask vertex array for stencil buffer to subtract
        maskVert = np.array(
            [[0, 0, 0],
             [printer.width*printer.pixel, 0, 0],
             [printer.width*printer.pixel, printer.height*printer.pixel, 0],
     
             [0, 0, 0],
             [printer.width*printer.pixel, printer.height*printer.pixel, 0],
             [0, printer.height*printer.pixel, 0]], dtype=GLfloat
        )
    
        #######################################
        # make VAO for drawing mask
        self.maskVAO = QtGui.QOpenGLVertexArrayObject()
        self.maskVAO.create()
        self.maskVAO.bind()
        
        self.maskVBO = QtGui.QOpenGLBuffer(QtGui.QOpenGLBuffer.VertexBuffer)
        self.maskVBO.create()
        self.maskVBO.bind()
        self.maskVBO.setUsagePattern(QtGui.QOpenGLBuffer.StaticDraw)
        data = maskVert.tostring()
        self.maskVBO.allocate(data, len(data))
        self.gl.glVertexAttribPointer(0, 3, self.gl.GL_FLOAT, 
            self.gl.GL_FALSE, 3*sizeof(GLfloat), 0)
        self.gl.glEnableVertexAttribArray(0)
        
        self.maskVBO.release()
        self.maskVAO.release()
        #######################################
        
    def paintGL(self):
        if self.height >= self.totalThickness-EPSILON:
            sys.exit()
        else:
            self.height += self.layerThickness
            self.currentLayer += 1
            self.draw()
            self.renderSlice()
            self.update()
        
    def draw(self):
        self.gl.glViewport(0, 0, self.size().width(), self.size().height())
        self.gl.glEnable(self.gl.GL_STENCIL_TEST)
        self.gl.glClearColor(0., 0., 0., 1.)
        self.gl.glClear(self.gl.GL_COLOR_BUFFER_BIT | self.gl.GL_STENCIL_BUFFER_BIT)
        self.vertVAO.bind()
        self.shaderProg.bind()
        
        self.model.translate(0, 0, -self.layerThickness)
        self.shaderProg.setUniformValue('proj', self.proj)
        self.shaderProg.setUniformValue('model', self.model)
        
        self.gl.glEnable(self.gl.GL_CULL_FACE)
        self.gl.glCullFace(self.gl.GL_FRONT)
        self.gl.glStencilFunc(self.gl.GL_ALWAYS, 0, 0xFF)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_INCR)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, self.numOfVerts)

        self.gl.glCullFace(self.gl.GL_BACK)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_DECR)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, self.numOfVerts)
        self.gl.glDisable(self.gl.GL_CULL_FACE)

        self.gl.glClear(self.gl.GL_COLOR_BUFFER_BIT)
        self.maskVAO.bind()
        self.gl.glStencilFunc(self.gl.GL_NOTEQUAL, 0, 0xFF)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_KEEP)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, 6)
        self.gl.glDisable(self.gl.GL_STENCIL_TEST)
        self.shaderProg.release()
        
    def renderSlice(self):
        self.sliceFbo.bind()
        self.gl.glViewport(0, 0, printer.width, printer.height)
        self.gl.glEnable(self.gl.GL_STENCIL_TEST)
        self.gl.glClearColor(0., 0., 0., 1.)
        self.gl.glClear(self.gl.GL_COLOR_BUFFER_BIT | self.gl.GL_STENCIL_BUFFER_BIT)
        self.vertVAO.bind()
        self.shaderProg.bind()
        
        self.shaderProg.setUniformValue('proj', self.proj)
        self.shaderProg.setUniformValue('model', self.model)
        
        self.gl.glEnable(self.gl.GL_CULL_FACE)
        self.gl.glCullFace(self.gl.GL_FRONT)
        self.gl.glStencilFunc(self.gl.GL_ALWAYS, 0, 0xFF)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_INCR)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, self.numOfVerts)

        self.gl.glCullFace(self.gl.GL_BACK)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_DECR)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, self.numOfVerts)
        self.gl.glDisable(self.gl.GL_CULL_FACE)

        self.gl.glClear(self.gl.GL_COLOR_BUFFER_BIT)
        self.maskVAO.bind()
        self.gl.glStencilFunc(self.gl.GL_NOTEQUAL, 0, 0xFF)
        self.gl.glStencilOp(self.gl.GL_KEEP, self.gl.GL_KEEP, self.gl.GL_KEEP)
        self.gl.glDrawArrays(self.gl.GL_TRIANGLES, 0, 6)
        self.gl.glDisable(self.gl.GL_STENCIL_TEST)
        
        image = self.sliceFbo.toImage()
        # makes a QComboBox for different Image Format,
        # namely Format_Mono, Format_MonoLSB, and Format_Grayscale8
        image = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
        image.save(os.path.join(self.sliceSavePath,
                                'out{:04d}.png'.format(self.currentLayer)))
        self.sliceFbo.release()
        
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            sys.exit()
        event.accept()


def main():
    
    sltFilename = sys.argv[1]
    layerThickness = float(sys.argv[2])
    temp = os.path.dirname(sltFilename)
    sliceSavePath = os.path.join(temp, 'slices')
    if not os.path.exists(sliceSavePath):
        os.mkdir(sliceSavePath)
        
    app = QtWidgets.QApplication(sys.argv)
    window = Window(sltFilename, layerThickness, sliceSavePath)
    window.resize(SCR_WIDTH, SCR_HEIGHT)
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()





















