<h2 style="text-align:center;margin:40px 0 0 0;border-bottom:none">Notepad++ Nginx User-defined Language</h2>

<h3 style="text-align:center;margin:0 0 40px 0">Syntax Highlighting for Nginx Configuration Files</h3>

<div style="text-align:center;width:50%;float:left">
	<div style="width:212px;height:153px;margin:0 auto">
		<a href="http://notepad-plus-plus.org" style="display: block; width: 212px; height: 153px; text-indent: -9999em; background-image: url(http://notepad-plus-plus.org/assets/img/logo-green-orange.png); background-attachment: initial; background-origin: initial; background-clip: initial; background-color: initial; background-position: 0px 0px; background-repeat: no-repeat no-repeat; " onmouseover="this.style.backgroundPosition = '0 -153px'" onmouseout="this.style.backgroundPosition = '0 0'">
			<img src="http://notepad-plus-plus.org/assets/img/logo-green-orange.png" alt="Notepad++">
		</a>
	</div>
</div>

<div style="text-align:center;width:50%;float:right">
	<a href="http://nginx.org/"><img src="http://wiki.nginx.org/local/nginx-logo.png" alt="Nginx"></a>
</div>

<div style="clear:both;width:100%;height:40px"></div>

<h4>Installation Instructions</h4>

1. Save *`userDefineLang.xml`* to your computer
2. Open Notepad++
3. Click *View* > *User-defined Dialogue...*
4. Click *Import* and navigation to *`userDefineLang.xml`*
5. Import it and restart Notepad++
6. Open an Nginx config file (e.g., /etc/nginx/nginx.conf)
7. If you already have the ".conf" extension assigned to another syntax highlighter, you'll need to select the Nginx hilighter explicitly by clicking *Language* > *Nginx* 

<p>*NOTE:* this language file only highlights the directives listed on the <a href="http://wiki.nginx.org/HttpCoreModule#Directives">HttpCoreModule</a> page at the time of writing. If you notice some directives aren't being highlighted, you can open the *User-Defined Dialogue* menu again and add them to the list under the *Keywords List* tab.</p>

<p style="text-align:center">For information on configuring user-defined language files, see <a href="http://sourceforge.net/apps/mediawiki/notepad-plus/index.php?title=User_Defined_Languages">User Defined Language Files</a>.</p>
