<?xml version="1.0" encoding="UTF-8"?>
<!--
Retourne le XML à l'identique. Prend des paramètres inutiles.
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:gmd="http://www.isotc211.org/2005/gmd"
                exclude-result-prefixes="#all">

  <xsl:param name="language-optional" select="'eng'"/>
  <xsl:param name="language-required" required="yes" select="'eng'"/>
  <xsl:param name="language-no-default" required="yes" />

  <!-- Do a copy of every nodes and attributes -->
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

</xsl:stylesheet>
