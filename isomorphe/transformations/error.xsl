<?xml version="1.0" encoding="UTF-8"?>
<!--
Retourne systematiquement une erreur.
-->

<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0"
                xmlns:gmd="http://www.isotc211.org/2005/gmd"
                xmlns:geonet="http://www.fao.org/geonetwork"
                exclude-result-prefixes="#all">

  <xsl:template match="/">
    <xsl:message terminate="yes">Error: BOOM!</xsl:message>
  </xsl:template>

</xsl:stylesheet>
