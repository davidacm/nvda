#vision/__init__.py
#A part of NonVisual Desktop Access (NVDA)
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.
#Copyright (C) 2018 NV Access Limited

"""Framework to facilitate changes in how content is displayed on screen.
Three roles (types) of vision enhancement providers are supported:
	* Magnifier: to magnify the full screen or a part of it.
	* Highlighter: to highlight important areas of the screen (e.g. the focus, mouse or review position).
	* ColorEnhancer: to change the color presentation of the whole screen or a part of it.
A vision enhancement provider can implement either one or more of the above assistant functions.
Plugins can register their own implementation for any or all of these
using L{registerProviderCls}.
"""

import config
from baseObject import AutoPropertyObject
from abc import abstractmethod
import api
import config
import weakref
from logHandler import log
import wx
from collections import defaultdict, OrderedDict
import textInfos
import NVDAObjects
import winVersion
from locationHelper import RectLTRB
from synthDriverHandler import StringParameterInfo
import textInfos
import treeInterceptorHandler

CONTEXT_UNDETERMINED = "undetermined"
CONTEXT_FOCUS = "focus"
CONTEXT_FOREGROUND = "foreground"
CONTEXT_CARET = "caret"
CONTEXT_REVIEW = "review"
CONTEXT_NAVIGATOR = "navigatorObj"
CONTEXT_MOUSE = "mouse"

ROLE_MAGNIFIER = "magnifier"
ROLE_HIGHLIGHTER = "highlighter"
ROLE_COLORENHANCER = "colorEnhancer"

_visionEnhancementProviders = set()

class VisionEnhancementProvider(AutoPropertyObject):
	name = ""
	description = ""
	#: The roles that would cause conflicts with this provider when initialized.
	#: Providers for conflicting roles are always terminated before initializing the provider.
	#: For example, if a color enhancer is used to make the screen black,
	#: It does not make sense to magnify the screen or use a highlighter.
	conflictingRoles = frozenset()
	_instance = None
	guiPanelCls = None
	cachePropertiesByDefault = True

	@classmethod
	def check(cls):
		return True

	@classmethod
	def __new__(cls, *args, **kwargs):
		# Make this a singleton.
		inst = cls._instance() if cls._instance else None
		if not inst:
			obj = super(VisionEnhancementProvider, cls).__new__(cls, *args, **kwargs)
			obj.activeRoles = set()
			cls._instance = weakref.ref(obj)
			return obj
		return inst

	def __init__(self, *roles):
		"""Constructor.
		Subclasses may extend this method.
		They must extend this method if additional initialization has to be performed before all roles are initialized.
		"""
		super(VisionEnhancementProvider, self).__init__()
		if not roles:
			roles = self.supportedRoles
		for role in roles:
			if role not in self.supportedRoles:
				raise RuntimeError("Role %s not supported by %s" % (role, self.name))
			if role in self.activeRoles:
				log.debug("Role %s for provider %s is already initialized, silently ignoring" % (role, self.name))
				continue
			getattr(self, "initialize%s" % (role[0].upper()+role[1:]))()
			self.activeRoles.add(role)

	@classmethod
	def _get_supportedRoles(cls):
		"""Returns the roles supported by this provider."""
		return frozenset(role for role, baseCls in ROLE_TO_CLASS_MAP.iteritems() if issubclass(cls, baseCls))

	def _get_running(self):
		"""Returns whether the provider is running.
		This is required for third party software, which runs in a separate process.
		Providers that run out of the NVDA process should override this method.
		"""
		return True

	def _get_enabled(self):
		"""Returns whether the provider is enabled.
		This differs from L{running}, as a provider could be temporarily disabled
		while still active in the background.
		By convension, this should always return C{False} when not running.
		"""
		return self.running and bool(self.activeRoles)

	@classmethod
	def getContextObject(cls, context):
		"""Gets the appropriate NVDAObject associated with the provided context."""
		if context == CONTEXT_FOCUS:
			return api.getFocusObject()
		elif context == CONTEXT_FOREGROUND:
			return api.getForegroundObject()
		elif context == CONTEXT_CARET:
			obj = api.getCaretObject()
		elif context == CONTEXT_REVIEW:
			return api.getReviewPosition().obj
		elif context == CONTEXT_NAVIGATOR:
			return api.getNavigatorObject()
		elif context == CONTEXT_MOUSE:
			return api.getMouseObject()
		else:
			raise NotImplementedError("Couldn't get object for context %s" % context)

	@classmethod
	def getContextRect(cls, context, obj=None):
		"""Gets a rectangle for the specified context.
		If L{obj} is not C{None}, the object is used to get the rectangle from.
		Otherwise, the base implementation calls L{getContextObject} and gets a rectangle from the object, if necessary."""
		if not obj:
			obj = cls.getContextObject(context)
		if not obj:
			raise LookupError
		if context == CONTEXT_CARET:
			if getattr(obj, "treeInterceptor", None) and not obj.treeInterceptor.passThrough:
				obj = obj.treeInterceptor
			elif isinstance(obj, NVDAObjects.NVDAObject):
				# Import late to avoid circular import
				from displayModel import getCaretRect
				# Check whether there is a caret in the window.
				# Note that, even windows that don't have navigable text could have a caret, such as in Excel.
				try:
					return RectLTRB.fromCompatibleType(getCaretRect(obj))
				except RuntimeError:
					if not obj._hasNavigableText:
						return None
			try:
				caretInfo = obj.makeTextInfo(textInfos.POSITION_CARET)
			except NotImplementedError:
				# There is nothing to do here
				raise LookupError
			return cls._getRectFromTextInfo(caretInfo)
		elif context == CONTEXT_REVIEW:
			return cls._getRectFromTextInfo(api.getReviewPosition())
		location = obj.location
		if not location:
			raise LookupError
		return location.toLTRB()

	@classmethod
	def _getRectFromTextInfo(cls, textInfo):
		if textInfo.isCollapsed:
			textInfo.expand(textInfos.UNIT_CHARACTER)
		try:
			rect = textInfo.boundingRect.toLTRB()
		except (LookupError, NotImplementedError):
			rect = RectLTRB.fromPoint(textInfo.pointAtStart)
		return rect

	def terminate(self, *roles):
		"""Executed when terminating this provider.
		Subclasses may extend this method.
		They must extend this method if additional cleanup has to be performed when all roles are terminated.
		"""
		if not roles:
			roles = self.activeRoles.copy()
		for role in roles:
			if role not in self.supportedRoles:
				raise RuntimeError("Role %s not supported by %s" % (role, self.name))
			if role not in self.activeRoles:
				log.debug("Role %s for provider %s is not initialized, silently ignoring" % (role, self.name))
				continue
			getattr(self, "terminate%s" % (role[0].upper()+role[1:]))()
			self.activeRoles.remove(role)

class Highlighter(VisionEnhancementProvider):
	#: Tuple of supported contexts for this highlighter.
	supportedHighlightContexts = tuple()

	@abstractmethod
	def initializeHighlighter(self):
		"""Initializes a highlighter.
		Subclasses must extend this method.
		"""
		#: A dictionary that maps contexts to their current rectangle.
		self.contextToRectMap = {}
		# Initialize the map with their current values
		for context in self.enabledHighlightContexts:
			# Always call the base implementation here
			Highlighter.updateContextRect(self, context)

	@abstractmethod
	def terminateHighlighter(self):
		"""Terminates a highlighter.
		Subclasses must extend this method.
		"""
		self.contextToRectMap.clear()

	def updateContextRect(self, context, rect=None, obj=None):
		"""Updates the position rectangle of the highlight for the specified context.
		The base implementation updates the position in the L{contextToRectMap}.
		if rect and obj are C{None}, the position is retrieved from the object associated with the context.
		Otherwise, either L{obj} or L{rect} should be provided.
		Subclasses should extend or override this method if they want to get the context position in a different way.
		"""
		if context not in self.supportedHighlightContexts:
			raise NotImplementedError
		if rect is not None and obj is not None:
			raise ValueError("Only one of rect or obj should be provided")
		if rect is None:
			try:
				rect= self.getContextRect(context, obj)
			except (LookupError, NotImplementedError):
				rect = None
		self.contextToRectMap[context] = rect

	@abstractmethod
	def refresh(self):
		"""Refreshes the screen positions of the enabled highlights.
		This is called once in every core cycle.
		Subclasses must override this method.
		"""
		raise NotImplementedError

	def _get_enabledHighlightContexts(self):
		"""Gets the contexts for which the highlighter is enabled."""
		if not self.enabled:
			return ()
		return tuple(
			context for context in self.supportedHighlightContexts
			if config.conf['vision'][self.name]['highlight%s' % (context[0].upper() + context[1:])]
		)

class Magnifier(VisionEnhancementProvider):
	#: Tuple of supported contexts for this magnifier to track to.
	supportedTrackingContexts = tuple()

	@abstractmethod
	def initializeMagnifier(self):
		"""Initializes a magnifier.
		Subclasses must extend this method.
		"""

	@abstractmethod
	def terminateMagnifier(self):
		"""Terminates a magnifier.
		Subclasses must extend this method.
		"""

	def trackToObject(self, obj=None, context=CONTEXT_UNDETERMINED, area=None):
		"""Tracks the magnifier to the given object.
		If object is C{None}, the appropriate object is fetched automatically.
		The base implementation simply tracks to the location of the object.
		Subclasses may override this method to implement context specific behaviour.
		"""
		try:
			rect = self.getContextRect(context, obj)
		except (LookupError, NotImplementedError):
			rect = None
		if not rect:
			return
		self.trackToRectangle(rect, context=context, area=area)

	@abstractmethod
	def trackToRectangle(self, rect, context=CONTEXT_UNDETERMINED, area=None):
		"""Tracks the magnifier to the given rectangle."""
		raise NotImplementedError

	def trackToPoint(self, point, context=CONTEXT_UNDETERMINED, area=None):
		"""Tracks the magnifier to the given point.
		The base implementation creates a rectangle from a point and tracks to that rectangle."""
		x, y = point
		rect = RectLTRB(x, y, x+1, y+1)
		self.trackToRectangle((rect), context=context, area=area)

	_abstract_magnificationLevel = True
	def _get_magnificationLevel(self):
		raise NotImplementedError

	def _set_magnificationLevel(self, level):
		raise NotImplementedError

	def _get_isMagnifying(self):
		"""Returns C{True} if the magnifier is magnifying the screen, C{False} otherwise.
		By default, this property is based on L{enabled} and L{magnificationLevel}
		"""
		return self.enabled and self.magnificationLevel > 1.0

	def _get_enabledTrackingContexts(self):
		"""Gets the contexts for which the magnifier is enabled."""
		if not self.isMagnifying:
			return ()
		return tuple(
			context for context in self.supportedTrackingContexts
			if config.conf['vision'][self.name]['trackTo%s' % (context[0].upper() + context[1:])]
		)

class ColorTransformationInfo(StringParameterInfo):
	"""Represents a color transformation.
	"""

	def __init__(self,ID,name,value):
		#: The value that cointains the color transformation info (e.g. a matrix).
		self.value=value
		super(ColorTransformationInfo,self).__init__(ID,name)

class ColorEnhancer(VisionEnhancementProvider):

	@abstractmethod
	def initializeColorEnhancer(self):
		"""Initializes a color enhancer.
		Subclasses must extend this method.
		"""

	@abstractmethod
	def terminateColorEnhancer(self):
		"""Terminates a color enhancer.
		Subclasses must extend this method.
		"""

	@abstractmethod
	def _getAvailableTransformations(self):
		"""Returns the color transformations supported by this color enhancer.
		@rtype: [L{ColorTransformationInfo}]
		"""
		raise NotImplementedError

	def _get_availableTransformations(self):
		return OrderedDict((info.ID,info) for info in self._getAvailableTransformations())

	_abstract_transformation = True
	def _get_transformation(self):
		raise NotImplementedError

	def _set_transformation(self, transformation):
		raise NotImplementedError

ROLE_TO_CLASS_MAP = {
	ROLE_MAGNIFIER: Magnifier,
	ROLE_HIGHLIGHTER: Highlighter,
	ROLE_COLORENHANCER: ColorEnhancer,
}

ROLE_DESCRIPTIONS = {
	# Translators: The name for a vision enhancement provider that magnifies one or more parts of the screen.
	ROLE_MAGNIFIER: _("Magnifier"),
	# Translators: The name for a vision enhancement provider that highlights important areas on screen,
	# such as the focus, caret or review cursor location.
	ROLE_HIGHLIGHTER: _("Highlighter"),
	# Translators: The name for a vision enhancement provider that enhances the color presentation.
	# (i.e. color inversion, gray scale coloring, etc.)
	ROLE_COLORENHANCER: _("Color enhancer"),
}

def getProviderList(excludeNegativeChecks=True):
	"""Gets a list of available vision enhancement names with their descriptions as well as supported and conflicting roles.
	@param excludeNegativeChecks: excludes all providers for which the check method returns C{False}.
	@type excludeNegativeChecks: bool
	@return: list of tuples with provider names, descriptions, supported roles and conflicting roles.
	@rtype: [(str,unicode,[ROLE_*],[ROLE_*])]
	"""
	providerList = []
	for provider in _visionEnhancementProviders:
		if not excludeNegativeChecks or provider.check():
			providerList.append((provider.name, provider.description, list(provider.supportedRoles), list(provider.conflictingRoles)))
		else:
			log.debugWarning("Vision enhancement provider %s reports as unavailable, excluding" % provider.name)
	providerList.sort(key=lambda d : d[1].lower())
	return providerList

class VisionHandler(AutoPropertyObject):
	cachePropertiesByDefault = True

	def __init__(self):
		self.lastReviewMoveContext = None
		self.lastCaretObjRef = None
		configuredProviders = defaultdict(set)
		for role in ROLE_TO_CLASS_MAP.iterkeys():
			setattr(self, role, None)
			configuredProviders[config.conf['vision'][role]].add(role)
		for name, roles in configuredProviders.iteritems():
			if name:
				wx.CallAfter(self.setProvider, name, *roles)
		config.post_configProfileSwitch.register(self.handleConfigProfileSwitch)

	def terminateProviderForRole(self, role):
		curProvider = getattr(self, role)
		if curProvider:
			curProvider.terminate(role)
			setattr(self, role, None)

	def setProvider(self, name, *roles, **kwargs):
		"""Enables and activates the selected provider for the provided roles.
		If there was a previous provider in use for a role,
		that provider will be terminated for that role.
		If another provider has to be terminated because of conflicting roles set for the new provider,
		a RuntimeError is raised.
		@param name: The name of the registered provider class.
		@type name: str
		@param roles: names of roles to enable the provider for.
			Supplied values should be one of the C{ROLE_*} constants.
			If no roles are provided, the provider is enabled for all the roles it supports.
		@type roles: str
		@param temporary: Whether the selected provider is enabled temporarily (e.g. as a fallback).
			Since this method uses a catch all handler for arguments,
			this parameter should always be provided as a keyword argument.
		@type temporary: bool
		@raise RuntimeError: If a provider couldn't be loaded due to conflicts.
		"""
		temporary = kwargs.pop("temporary", False)
		if name in (None, "None"):
			if not roles:
				raise ValueError("No name and no roles provided")
			for role in roles:
				try:
					self.terminateProviderForRole(role)
				except:
					log.error("Couldn't terminate provider for role %s" % role)
				if not temporary:
					config.conf['vision'][role] = None
			return True
		providerCls = getProviderCls(name)
		if not roles:
			roles = providerCls.supportedRoles
		else:
			roles = set(roles)
			for role in roles:
				if role not in providerCls.supportedRoles:
					raise NotImplementedError("Provider %s does not implement role %s" % (name, role))

		try:
			conflicts = {name for name in (getattr(self, role) for role in providerCls.conflictingRoles) if name}
			if conflicts:
				raise RuntimeError("Provider %s couldn't be activated because of conflicts with provider(s) %s." %
					(providerCls.name, ", ".join(conflict.name for conflict in conflicts))
				)

			# Providers are singletons.
			# Get a new or current instance of the provider
			providerInst = providerCls.__new__(providerCls)
			if providerInst.enabled:
				log.debug("Provider %s is already active" % name)
			# Terminate the provider for the roles that overlap between the provided roles and the active roles.
			overlappingRoles =  providerInst.activeRoles & roles
			newRoles =  roles - overlappingRoles
			if overlappingRoles:
				providerInst.terminate(*overlappingRoles)
			# Properly terminate  conflicting providers.
			for conflict in newRoles:
				self.terminateProviderForRole(conflict)
				if not temporary:
					config.conf['vision'][conflict] = None
			# Initialize the provider for the new and overlapping roles
			providerInst.__init__(*roles)
			# Assign the new provider to the new roles.
			for role in newRoles:
				setattr(self, role, providerInst)
				if not temporary:
					config.conf['vision'][role] = providerCls.name
			self.initialFocus()
			return True
		except:
			log.error("Error initializing vision enhancement provider %s for roles %s" % (name, ", ".join(roles)), exc_info=True)
			self.setProvider(None, *roles, temporary=True)
			return False

	def _get_initializedProviders(self):
		return tuple(
			provider for provider in (self.magnifier, self.highlighter, self.colorEnhancer)
			if provider
		)

	def _get_enabled(self):
		return bool(self.initializedProviders)

	def terminate(self):
		config.post_configProfileSwitch.unregister(self.handleConfigProfileSwitch)
		for role in ROLE_TO_CLASS_MAP.iterkeys():
			self.terminateProviderForRole(role)

	def handleUpdate(self, obj):
		if not self.enabled:
			return
		if obj is api.getFocusObject():
			context = CONTEXT_FOCUS
			if self.magnifier and context in self.magnifier.enabledTrackingContexts:
				self.magnifier.trackToObject(obj, context=context)
			if self.highlighter and context in self.highlighter.enabledHighlightContexts:
				self.highlighter.updateContextRect(context, obj=obj)
		elif obj is api.getNavigatorObject():
			self.handleReviewMove(context=CONTEXT_NAVIGATOR)

	def handleForeground(self, obj):
		context = CONTEXT_FOREGROUND
		if self.magnifier and context in self.magnifier.enabledTrackingContexts:
			self.magnifier.trackToObject(obj, context=context)
		if self.highlighter and context in self.highlighter.enabledHighlightContexts:
			self.highlighter.updateContextRect(context, obj=obj)

	def handleGainFocus(self, obj):
		context = CONTEXT_CARET if isinstance(obj, treeInterceptorHandler.TreeInterceptor) else CONTEXT_FOCUS
		if self.magnifier and context in self.magnifier.enabledTrackingContexts:
			self.magnifier.trackToObject(obj, context=context)
		if self.highlighter and context in self.highlighter.enabledHighlightContexts:
			if context != CONTEXT_CARET:
				self.highlighter.updateContextRect(context, obj=obj)
			if CONTEXT_CARET in self.highlighter.enabledHighlightContexts:
				# Check whether this object has a caret.
				# If it has one, update the caret highlight.
				# If it hasn't, clear the caret rectangle from the map
				self.highlighter.updateContextRect(CONTEXT_CARET, obj=obj)

	def handleCaretMove(self, obj):
		if not self.enabled:
			return
		self.lastCaretObjRef = weakref.ref(obj)

	def handlePendingCaretUpdate(self):
		if not callable(self.lastCaretObjRef):
			# No caret change
			return
		obj = self.lastCaretObjRef()
		if not obj:
			# The caret object died
			self.lastCaretObjRef = None
			return
		context = CONTEXT_CARET
		try:
			if self.magnifier and context in self.magnifier.enabledTrackingContexts:
				self.magnifier.trackToObject(obj, context=context)
			if self.highlighter and context in self.highlighter.enabledHighlightContexts:
				self.highlighter.updateContextRect(context, obj=obj)
		finally:
			self.lastCaretObjRef = None

	def handleReviewMove(self, context=CONTEXT_REVIEW):
		if not self.enabled:
			return
		self.lastReviewMoveContext = context

	def handlePendingReviewUpdate(self):
		if self.lastReviewMoveContext is None:
			# No review change.
			return
		lastReviewMoveContext = self.lastReviewMoveContext
		self.lastReviewMoveContext = None
		if lastReviewMoveContext in (CONTEXT_NAVIGATOR, CONTEXT_REVIEW) and self.magnifier and lastReviewMoveContext in self.magnifier.enabledTrackingContexts:
			self.magnifier.trackToObject(context=lastReviewMoveContext)
		if self.highlighter:
			for context in (CONTEXT_NAVIGATOR, CONTEXT_REVIEW):
				if context in self.highlighter.enabledHighlightContexts:
					self.highlighter.updateContextRect(context=context)

	def handleMouseMove(self, obj, x, y):
		# Mouse moves execute once per core cycle.
		if self.magnifier and CONTEXT_MOUSE in self.magnifier.enabledTrackingContexts:
			self.magnifier.trackToPoint((x, y), context=CONTEXT_MOUSE)

	def handleConfigProfileSwitch(self):
		for role in ROLE_TO_CLASS_MAP.iterkeys():
			newProviderName = config.conf['vision'][role]
			curProvider = getattr(self, role)
			if  not curProvider or newProviderName != curProvider.name:
				self.setProvider(newProviderName, role)

	def initialFocus(self):
		if not self.enabled or not api.getDesktopObject():
			# No active providers or focus/review hasn't yet been initialised.
			return
		self.handleGainFocus(api.getFocusObject())

def initialize():
	# Register build in providers
	if (winVersion.winVersion.major, winVersion.winVersion.minor) >= (6, 2):
		from screenCurtain import WinMagnificationScreenCurtain as ScreenCurtain
		registerProviderCls(ScreenCurtain)
	from NVDAHighlighter import NVDAHighlighter
	registerProviderCls(NVDAHighlighter)
	global handler
	handler = VisionHandler()

def pumpAll():
	"""Runs tasks at the end of each core cycle."""
	# Note that a pending review update has to be executed before a pending caret update.
	handler.handlePendingReviewUpdate()
	handler.handlePendingCaretUpdate()

def registerProviderCls(providerCls):
	"""Register a vision enhancement provider class.
	@param providerCls: The provider to register.
	@type providerCls: subclass of L{VisionEnhancementProvider}
	"""
	global _visionEnhancementProviders
	_visionEnhancementProviders.add(providerCls)

def unregisterProviderCls(providerCls):
	"""Unregister a vision enhancement provider class.
	@param providerCls: The provider to unregister.
	@type providerCls: subclass of L{VisionEnhancementProvider}
	"""
	global _visionEnhancementProviders
	_visionEnhancementProviders.remove(providerCls)

def getProviderCls(name):
	"""Returns a registered provider class with the specified name."""
	try:
		return next(providerCls for providerCls in _visionEnhancementProviders if providerCls.name == name)
	except StopIteration:
		raise ValueError("Vision enhancement provider %s not registered" % name)

def terminate():
	global handler
	handler.terminate()
	handler = None
