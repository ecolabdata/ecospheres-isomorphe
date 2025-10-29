<?xml version="1.0" encoding="UTF-8"?>
<!--
Retourne systematiquement une erreur.
-->

<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:gmd="http://www.isotc211.org/2005/gmd"
                exclude-result-prefixes="#all">

  <xsl:template match="/">
    <xsl:message terminate="yes">Error: BOOM!</xsl:message>
  </xsl:template>

</xsl:stylesheet>
